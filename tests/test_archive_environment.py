import gzip
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from llm_benchmark.api import create_app
from llm_benchmark.cli import app
from llm_benchmark.domain import Result
from llm_benchmark.environment import hardware_inventory
from llm_benchmark.reports import stream_jsonl


def test_archive_snapshot_across_worker_threads(store, frozen):
    id = store.create_run(frozen.set_id, store.get_model("mock-reference"))
    rows = stream_jsonl(store, id)
    with ThreadPoolExecutor(max_workers=1) as first:
        header = json.loads(first.submit(next, rows).result())
    attempt = store.begin_attempt(id, 0)
    store.save_result(
        id,
        Result(
            index=0,
            problem_id=frozen.problems[0].problem_id,
            status="correct",
            correct=True,
            answer="fixture",
            reason="ok",
            latency_seconds=1,
        ),
        attempt,
    )
    with ThreadPoolExecutor(max_workers=1) as second:
        remaining = second.submit(list, rows).result()
    records = [json.loads(line) for line in remaining]
    assert header["export_schema"] == "forge-stream-v1"
    assert len(records) == len(frozen.problems)
    assert all(r["type"] == "problem" and "answer_spec" in r for r in records)
    updated = [json.loads(line) for line in stream_jsonl(store, id)]
    assert [r["type"] for r in updated[-2:]] == ["result", "attempt"]


def test_archive_http_and_exclusive_gzip(store, frozen, monkeypatch, tmp_path):
    id = store.create_run(frozen.set_id, store.get_model("mock-reference"))
    with TestClient(create_app(store.path.parent), base_url="http://127.0.0.1") as client:
        response = client.get(f"/api/runs/{id}/archive")
        assert response.status_code == 200
        assert len(response.text.splitlines()) == len(frozen.problems) + 1
        assert client.get("/api/runs/missing/archive").status_code == 404
    monkeypatch.setenv("FORGE_DATA_DIR", str(store.path.parent))
    path = tmp_path / "archive.jsonl.gz"
    runner = CliRunner()
    assert runner.invoke(app, ["archive", id, str(path), "--compress"]).exit_code == 0
    original = path.read_bytes()
    assert runner.invoke(app, ["archive", id, str(path), "--compress"]).exit_code == 1
    assert path.read_bytes() == original
    with gzip.open(path, "rt") as file:
        assert json.loads(file.readline())["id"] == id


@pytest.mark.parametrize("mode", ["missing", "valid", "failure", "malformed"])
def test_gpu_inventory_is_optional_and_cached(monkeypatch, mode):
    hardware_inventory.cache_clear()
    monkeypatch.setattr(
        "llm_benchmark.environment.shutil.which",
        lambda _: None if mode == "missing" else "/usr/bin/nvidia-smi",
    )
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        assert kwargs["timeout"] == 2
        assert "shell" not in kwargs
        if mode == "failure":
            raise subprocess.TimeoutExpired(args, 2)
        return SimpleNamespace(stdout="Fixture GPU, 999, 4096\n" if mode == "valid" else "bad\n")

    monkeypatch.setattr("llm_benchmark.environment.subprocess.run", run)
    try:
        value = hardware_inventory()
        assert hardware_inventory() is value
        assert len(calls) == (0 if mode == "missing" else 1)
        if mode == "valid":
            assert value["gpu_devices"][0]["total_vram_bytes"] == 4096 * 1048576
            assert value["gpu_inventory_reason"] is None
        else:
            assert value["gpu_devices"] is None
            assert value["gpu_inventory_reason"]
    finally:
        hardware_inventory.cache_clear()
