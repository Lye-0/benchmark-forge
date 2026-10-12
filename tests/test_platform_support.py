import asyncio
import json
import os
import subprocess
import sys

import psutil
import pytest

from llm_benchmark.domain import ModelConfig, PublicProblem
from llm_benchmark.platform_support import acquire_lock, peak_ram, release_lock, worker_environment
from llm_benchmark.transformers_adapter import TransformersAdapter


def test_lock_across_processes_crash_release_and_unicode_path(tmp_path):
    path = tmp_path / "日本語 空白" / "runner.lock"
    path.parent.mkdir()
    code = """import sys
from pathlib import Path
from llm_benchmark.platform_support import acquire_lock
try:
 lock=acquire_lock(Path(sys.argv[1]))
except OSError:
 sys.exit(19)
"""
    lock = acquire_lock(path)
    try:
        assert subprocess.run([sys.executable, "-c", code, str(path)], timeout=10).returncode == 19
    finally:
        release_lock(lock)
    # Process exit releases an OS lock even without explicit release.
    assert subprocess.run([sys.executable, "-c", code, str(path)], timeout=10).returncode == 0
    again = acquire_lock(path)
    release_lock(again)


def test_worker_environment_and_peak_are_host_specific(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "secret-fixture")
    monkeypatch.setenv("PYTHONPATH", "injection-fixture")
    env = worker_environment()
    assert "HF_TOKEN" not in env and "PYTHONPATH" not in env
    assert env["PYTHONUTF8"] == "1" and env["HF_HUB_OFFLINE"] == "1"
    if sys.platform == "win32":
        assert env["SYSTEMROOT"] == os.environ["SYSTEMROOT"]
    value, scope = peak_ram()
    assert value is not None and value > 0
    assert ("Windows" if sys.platform == "win32" else "Linux") in scope


async def test_worker_cancellation_terminates_descendant(monkeypatch, tmp_path):
    # Trusted synthetic worker; no LLM-generated code is executed on the host.
    pid_file = tmp_path / "child.json"
    fixture = tmp_path / "worker.py"
    fixture.write_text(
        """import sys,subprocess,json,time
from pathlib import Path
request=json.load(sys.stdin)
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
Path(request['problem']['prompt']).write_text(json.dumps(child.pid))
time.sleep(60)
""",
        encoding="utf-8",
    )
    original = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        return await original(sys.executable, str(fixture), **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    adapter = TransformersAdapter(
        ModelConfig(model_id="fixture", name="fixture", backend="transformers", timeout_seconds=10)
    )
    task = asyncio.create_task(
        adapter.complete(PublicProblem(problem_id="fixture", prompt=str(pid_file)))
    )
    child = None

    def running(process):
        try:
            return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False

    try:
        async with asyncio.timeout(10):
            while not pid_file.exists():
                if task.done():
                    await task
                await asyncio.sleep(0.02)
        child = psutil.Process(json.loads(pid_file.read_text(encoding="utf-8")))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with asyncio.timeout(5):
            while running(child):
                await asyncio.sleep(0.02)
    finally:
        task.cancel()
        if child and running(child):
            child.kill()


async def test_cancellation_during_worker_creation_reaps_process(monkeypatch):
    original = asyncio.create_subprocess_exec
    created, release = asyncio.Event(), asyncio.Event()
    processes = []

    async def delayed(*args, **kwargs):
        proc = await original(sys.executable, "-c", "import sys;sys.stdin.read()", **kwargs)
        processes.append(proc)
        created.set()
        await release.wait()
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed)
    adapter = TransformersAdapter(
        ModelConfig(model_id="fixture", name="fixture", backend="transformers")
    )
    task = asyncio.create_task(
        adapter.complete(PublicProblem(problem_id="fixture", prompt="fixture"))
    )
    await created.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert processes[0].returncode is not None


def test_torch_probe_cpu_and_cuda_without_models(monkeypatch):
    from types import SimpleNamespace

    from llm_benchmark.torch_probe import probe

    cuda = SimpleNamespace(is_available=lambda: False, device_count=lambda: 0)
    torch = SimpleNamespace(__version__="fixture", version=SimpleNamespace(cuda=None), cuda=cuda)
    monkeypatch.setattr("llm_benchmark.torch_probe.importlib.import_module", lambda _: torch)
    assert probe()["cuda_available"] is False
    cuda.is_available = lambda: True
    cuda.device_count = lambda: 1
    cuda.get_device_name = lambda i: "fixture GPU"
    cuda.get_device_properties = lambda i: SimpleNamespace(total_memory=1024)
    value = probe()
    assert value["cuda_available"] and value["devices"][0]["total_vram_bytes"] == 1024
    assert not value["live_model_verified"]


def test_missing_torch_is_optional(monkeypatch):
    from llm_benchmark.environment import torch_status

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], stderr=b"secret-fixture")

    monkeypatch.setattr("llm_benchmark.environment.subprocess.run", fail)
    value = torch_status()
    assert not value["available"] and value["cuda_available"] is None
    assert "secret-fixture" not in str(value)
