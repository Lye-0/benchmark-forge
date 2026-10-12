import asyncio
import os

import pytest

from llm_benchmark.code_eval import CodeConfig, build_code_set
from llm_benchmark.runner import Scheduler, summarize
from llm_benchmark.sandbox import DockerSandbox, IsolationUnavailable, command


async def test_sandbox_fail_closed_without_verification():
    with pytest.raises(IsolationUnavailable):
        await DockerSandbox().execute("print(1)")
    with pytest.raises(ValueError):
        DockerSandbox("python:latest")


@pytest.fixture
async def verified_sandbox():
    if os.environ.get("FORGE_TEST_DOCKER") != "1":
        pytest.skip("実Docker検証はFORGE_TEST_DOCKER=1で明示実行")
    sandbox = DockerSandbox()
    status = await sandbox.verify()
    assert status["available"], status["reason"]
    return sandbox


async def test_real_limits_and_cleanup(verified_sandbox, tmp_path):
    sandbox = verified_sandbox
    sentinel = tmp_path / "host-sentinel"
    sentinel.write_text("non-secret fixture")
    result = await sandbox.execute(
        f"import os\nassert not os.path.exists({str(sentinel)!r})\nprint('blocked')"
    )
    assert result.status == "ok" and result.stdout.strip() == "blocked"
    result = await sandbox.execute("open('/tmp/too-large','wb').write(b'x'*2000000)")
    assert result.status == "error"
    result = await sandbox.execute("print('x'*100000)")
    assert result.status == "output_limit"
    result = await sandbox.execute("import time;time.sleep(30)", seconds=0.2)
    assert result.status == "timeout"
    result = await sandbox.execute(
        "import os,time\npids=[]\ntry:\n for i in range(40):\n  pid=os.fork()\n  if pid==0:\n   time.sleep(2);os._exit(0)\n  pids.append(pid)\nexcept OSError:\n print('pid-limit')\nfor pid in pids: os.waitpid(pid,0)"
    )
    assert result.status == "ok" and "pid-limit" in result.stdout
    task = asyncio.create_task(sandbox.execute("import time;time.sleep(30)"))
    await asyncio.sleep(0.4)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    rc, containers = await command("ps", "-aq", "--filter", "label=benchmark-forge=disposable")
    assert rc == 0 and not containers.strip()


async def test_code_evaluation_vertical_path(verified_sandbox, store):
    frozen = build_code_set(CodeConfig(count=2))
    store.save_set(frozen)
    scheduler = Scheduler(store)
    scheduler.sandbox = verified_sandbox
    scheduler.start()
    try:
        ids = scheduler.create(frozen.set_id, ["mock-reference", "mock-wrong"])
        await scheduler.queue.join()
        correct, wrong = [summarize(store, id) for id in ids]
        assert correct["correct"] == 2
        assert wrong["correct"] == 0
        assert correct["results"][0]["metrics"]["sandbox_status"] == "ok"
        assert "def solve" in correct["results"][0]["answer"]
    finally:
        await scheduler.close()


async def test_missing_docker_returns_unavailable(monkeypatch):
    async def missing(*args, **kwargs):
        raise FileNotFoundError("docker unavailable")

    monkeypatch.setattr("llm_benchmark.sandbox.command", missing)
    result = await DockerSandbox().verify()
    assert result["available"] is False


async def test_cleanup_failure_revokes_verification(monkeypatch):
    sandbox = DockerSandbox()
    sandbox.verified = True

    async def fail(*args, **kwargs):
        return 1, b""

    monkeypatch.setattr("llm_benchmark.sandbox.command", fail)
    with pytest.raises(IsolationUnavailable):
        await sandbox.execute("print(1)")
    assert not sandbox.verified


async def test_cancel_waits_for_inflight_creation_before_removal(monkeypatch):
    import json

    creating, finish = asyncio.Event(), asyncio.Event()
    order = []

    async def delayed(*args, **kwargs):
        if args[0] == "create":
            creating.set()
            await finish.wait()
            order.append("created")
            return 0, b"id"
        if args[0] == "rm":
            order.append("removed")
            return 0, b""
        return 0, json.dumps({}).encode()

    monkeypatch.setattr("llm_benchmark.sandbox.command", delayed)
    sandbox = DockerSandbox()
    sandbox.verified = True
    task = asyncio.create_task(sandbox.execute("print(1)"))
    await creating.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    assert order == []
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert order == ["created", "removed"]


@pytest.mark.parametrize(
    "mode,state",
    [
        ("stopped", "daemon_unavailable"),
        ("windows", "unsupported_engine"),
        ("limits", "verification_failed"),
    ],
)
async def test_engine_diagnostics_fail_closed(monkeypatch, mode, state):
    async def fixture(*args, **kwargs):
        if args[0] == "info":
            return (
                (1, b"")
                if mode == "stopped"
                else (0, b"windows" if mode == "windows" else b"linux")
            )
        return 1, b""

    monkeypatch.setattr("llm_benchmark.sandbox.command", fixture)
    sandbox = DockerSandbox()
    result = await sandbox.verify()
    assert result["state"] == state and not result["available"]
    with pytest.raises(IsolationUnavailable):
        await sandbox.execute("print('never on host')")
