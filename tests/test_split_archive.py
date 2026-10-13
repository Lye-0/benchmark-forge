import gzip
import json

import pytest
from typer.testing import CliRunner

from llm_benchmark.archive import split_archive, verify_archive
from llm_benchmark.cli import app
from llm_benchmark.domain import Result
from llm_benchmark.reports import stream_jsonl


@pytest.mark.parametrize("compress", [False, True])
def test_split_roundtrip_and_corruption(store, frozen, tmp_path, compress):
    run_id = store.create_run(frozen.set_id, store.get_model("mock-reference"))
    store.save_result(
        run_id,
        Result(
            index=0,
            problem_id=frozen.problems[0].problem_id,
            status="empty",
            correct=False,
            answer="",
            reason="日本語fixture",
            latency_seconds=1,
        ),
    )
    expected = "".join(stream_jsonl(store, run_id))
    output = tmp_path / "日本語 archive"
    manifest = split_archive(store, run_id, output, 3000, compress)
    assert len(manifest["parts"]) > 1
    assert manifest["records"] == 3 + len(frozen.problems)
    decoded = []
    for part in manifest["parts"]:
        data = (output / part["name"]).read_bytes()
        data = gzip.decompress(data) if compress else data
        assert len(data) == part["uncompressed_bytes"]
        assert len(data.splitlines()) == part["records"]
        assert len(data) <= 3000 or part["records"] == 1
        decoded.append(data.decode("utf-8"))
    assert "".join(decoded) == expected
    assert verify_archive(output)["verified"]
    with pytest.raises(FileExistsError):
        split_archive(store, run_id, output, 3000, compress)
    path = output / manifest["parts"][-1]["name"]
    original = path.read_bytes()
    path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    with pytest.raises(ValueError, match="SHA-256"):
        verify_archive(output)
    path.unlink()
    with pytest.raises(ValueError, match="存在しない"):
        verify_archive(output)


def test_failure_closes_snapshot_without_completion_manifest(store, frozen, tmp_path, monkeypatch):
    run_id = store.create_run(frozen.set_id, store.get_model("mock-reference"))
    rows = store.iter_export
    closed = []

    def interrupted(id):
        try:
            yield next(rows(id))
            raise OSError("fixture disk failure")
        finally:
            closed.append(True)

    monkeypatch.setattr(store, "iter_export", interrupted)
    output = tmp_path / "partial"
    with pytest.raises(OSError):
        split_archive(store, run_id, output, 3000, False)
    assert closed == [True]
    assert not (output / "manifest.json").exists()
    with pytest.raises(FileNotFoundError):
        verify_archive(output)


def test_cli_validation_and_untrusted_manifest(store, frozen, tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_DATA_DIR", str(store.path.parent))
    run_id = store.create_run(frozen.set_id, store.get_model("mock-reference"))
    output = tmp_path / "cli"
    runner = CliRunner()
    assert (
        runner.invoke(app, ["archive-split", run_id, str(output), "--part-mib", "0"]).exit_code != 0
    )
    assert not output.exists()
    assert runner.invoke(app, ["archive-split", run_id, str(output), "--compress"]).exit_code == 0
    assert runner.invoke(app, ["archive-verify", str(output)]).exit_code == 0
    path = output / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["parts"][0]["name"] = "../outside.jsonl.gz"
    path.write_text(json.dumps(manifest))
    assert runner.invoke(app, ["archive-verify", str(output)]).exit_code == 1
