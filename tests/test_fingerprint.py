import hashlib
import json

from typer.testing import CliRunner

from llm_benchmark.cli import app
from llm_benchmark.fingerprint import fingerprint_model


def test_model_fingerprint_is_portable_and_detects_content_changes(tmp_path):
    models = []
    for name in ("日本語 model", "copy"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "weights.safetensors").write_bytes(b"fixture weights")
        (directory / "config.json").write_text('{"fixture": true}')
        (directory / "README.md").write_text("not model input")
        (directory / "Z.json").write_text("{}")
        (directory / "a.json").write_text("{}")
        models.append(directory)
    a, b = [fingerprint_model(path) for path in models]
    assert a["manifest_sha256"] == b["manifest_sha256"]
    assert [row["path"] for row in a["files"]] == [
        "Z.json",
        "a.json",
        "config.json",
        "weights.safetensors",
    ]
    assert a["files"][3]["sha256"] == hashlib.sha256(b"fixture weights").hexdigest()
    (models[1] / "weights.safetensors").write_bytes(b"updated weights")
    assert fingerprint_model(models[1])["manifest_sha256"] != a["manifest_sha256"]


def test_fingerprint_cli_does_not_overwrite_or_pollute_model_directory(tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    (model / "weights.gguf").write_bytes(b"fixture")
    output = tmp_path / "manifest.json"
    runner = CliRunner()
    assert runner.invoke(app, ["model-fingerprint", str(model), str(output)]).exit_code == 0
    saved = output.read_bytes()
    assert json.loads(saved)["total_bytes"] == len(b"fixture")
    assert runner.invoke(app, ["model-fingerprint", str(model), str(output)]).exit_code == 1
    assert output.read_bytes() == saved
    inside = model / "manifest.json"
    assert runner.invoke(app, ["model-fingerprint", str(model), str(inside)]).exit_code == 1
    assert not inside.exists()


def test_change_during_read_is_rejected_without_output(tmp_path, monkeypatch):
    model = tmp_path / "weights.gguf"
    model.write_bytes(b"before")
    original = hashlib.file_digest

    def changed(stream, algorithm):
        result = original(stream, algorithm)
        model.write_bytes(b"changed after reading")
        return result

    monkeypatch.setattr(hashlib, "file_digest", changed)
    output = tmp_path / "manifest.json"
    result = CliRunner().invoke(app, ["model-fingerprint", str(model), str(output)])
    assert result.exit_code == 1
    assert not output.exists()


def test_links_and_special_files_are_not_followed(tmp_path):
    import os

    import pytest

    model = tmp_path / "model"
    model.mkdir()
    outside = tmp_path / "outside.gguf"
    outside.write_bytes(b"fixture")
    link = model / "linked.gguf"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Symbolic links unavailable in this environment")
    with pytest.raises(ValueError, match="シンボリックリンク"):
        fingerprint_model(model)
    link.unlink()
    if hasattr(os, "mkfifo"):
        os.mkfifo(model / "pipe.json")
        with pytest.raises(ValueError, match="通常ファイル"):
            fingerprint_model(model)
