import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from llm_benchmark.cli import app
from llm_benchmark.fingerprint import fingerprint_model


def stat_fixture(info, **changes):
    """Keep real metadata while varying one OS-provided observation."""
    fields = ("st_mode", "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    return SimpleNamespace(**({key: getattr(info, key) for key in fields} | changes))


@pytest.mark.parametrize("use_cli", [False, True])
def test_windows_path_and_descriptor_ctime_can_differ(tmp_path, monkeypatch, use_cli):
    model = tmp_path / "日本語 weights.gguf"
    model.write_bytes(b"unchanged weights")
    expected = fingerprint_model(model)
    real_fstat = os.fstat

    def windows_fstat(fd):
        info = real_fstat(fd)
        # CPython 3.12 Windows: stat reports birth time, fstat reports change time.
        return stat_fixture(info, st_ctime_ns=info.st_ctime_ns + 1_000_000_000)

    monkeypatch.setattr(os, "fstat", windows_fstat)
    if use_cli:
        output = tmp_path / "manifest.json"
        result = CliRunner().invoke(app, ["model-fingerprint", str(model), str(output)])
        assert result.exit_code == 0, result.output
        actual = json.loads(output.read_text(encoding="utf-8"))
    else:
        actual = fingerprint_model(model)
    assert actual["manifest_sha256"] == expected["manifest_sha256"]
    assert actual["files"] == expected["files"]


@pytest.mark.parametrize("change", ["descriptor_ctime", "path_ctime", "path_identity"])
def test_metadata_only_change_during_read_is_rejected(tmp_path, monkeypatch, change):
    model = tmp_path / "weights.gguf"
    model.write_bytes(b"unchanged size and mtime")
    real_fstat, real_stat, real_digest = os.fstat, Path.stat, hashlib.file_digest
    read_finished = False

    def observed_fstat(fd):
        info = real_fstat(fd)
        # Different API meanings are normal; a later change within either API is not.
        return stat_fixture(
            info,
            st_ctime_ns=info.st_ctime_ns
            + 1_000_000_000
            + int(read_finished and change == "descriptor_ctime"),
        )

    def observed_stat(path, *args, **kwargs):
        info = real_stat(path, *args, **kwargs)
        if path == model and read_finished:
            if change == "path_ctime":
                return stat_fixture(info, st_ctime_ns=info.st_ctime_ns + 1)
            if change == "path_identity":
                return stat_fixture(info, st_ino=info.st_ino + 1)
        return info

    def finish_read(stream, algorithm):
        nonlocal read_finished
        result = real_digest(stream, algorithm)
        read_finished = True
        return result

    monkeypatch.setattr(os, "fstat", observed_fstat)
    monkeypatch.setattr(Path, "stat", observed_stat)
    monkeypatch.setattr(hashlib, "file_digest", finish_read)
    output = tmp_path / "manifest.json"
    result = CliRunner().invoke(app, ["model-fingerprint", str(model), str(output)])
    assert result.exit_code == 1
    assert "取得中にファイルが変更" in result.output
    assert not output.exists()


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
