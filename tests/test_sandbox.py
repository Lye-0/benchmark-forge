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


@pytest.mark.parametrize("mode", ["oom", "error", "inconsistent"])
async def test_attachment_eof_waits_for_final_container_state(monkeypatch, mode):
    import json

    ended = False
    operations = []

    async def fixture(*args, **kwargs):
        nonlocal ended
        operations.append(args[0])
        if args[0] == "inspect" and len(args) == 2:
            return 0, json.dumps(
                [
                    {
                        "Mounts": [],
                        "Config": {"User": "65534:65534"},
                        "HostConfig": {
                            "Privileged": False,
                            "NetworkMode": "none",
                            "PidMode": "",
                            "ReadonlyRootfs": True,
                            "Memory": 134217728,
                            "PidsLimit": 32,
                            "CapDrop": ["ALL"],
                        },
                    }
                ]
            ).encode()
        if args[0] == "wait":
            assert 0 < kwargs["timeout"] <= 5
            ended = True
            return 0, b"137\n" if mode == "oom" else b"42\n"
        if args[0] == "inspect":
            return 0, json.dumps(
                {
                    "Running": not ended or mode == "inconsistent",
                    "OOMKilled": ended and mode == "oom",
                    "ExitCode": (137 if mode == "oom" else 42) if ended else 0,
                }
            ).encode()
        # docker start attachment can finish successfully before the daemon's
        # terminal state is available; its return code is not the Python exit code.
        return 0, b""

    monkeypatch.setattr("llm_benchmark.sandbox.command", fixture)
    sandbox = DockerSandbox()
    if mode == "inconsistent":
        with pytest.raises(IsolationUnavailable, match="終了状態"):
            await sandbox._run("fixture")
    else:
        result = await sandbox._run("fixture")
        assert result.status == mode
        assert result.exit_code == (137 if mode == "oom" else 42)
    assert operations.index("wait") > operations.index("start")
    assert operations[-1] == "rm"


@pytest.mark.parametrize(
    "status,exit_code,evidence,available",
    [
        ("ok", 0, '{"child_exit": -9, "oom_kill_delta": 1}', True),
        ("oom", 0, '{"child_exit": -9, "oom_kill_delta": 1}', True),
        ("ok", 0, '{"child_exit": -9, "oom_kill_delta": 0}', False),
        ("ok", 0, '{"child_exit": 1, "oom_kill_delta": 1}', False),
        ("ok", 0, '{"child_exit": -9, "oom_kill_delta": true}', False),
        ("ok", 0, "malformed", False),
        ("error", 137, "", False),
        ("oom", 137, "", False),
        ("timeout", None, "", False),
    ],
)
async def test_verification_requires_cgroup_oom_evidence(
    monkeypatch, status, exit_code, evidence, available
):
    from llm_benchmark.sandbox import OOM_PROBE, CodeResult

    async def info(*args, **kwargs):
        return 0, b"linux"

    async def run(code, seconds=5):
        if code == OOM_PROBE:
            assert seconds == 10
            return CodeResult(status, evidence, exit_code)
        if code == "while True: pass":
            return CodeResult("error", "", 137)
        return CodeResult("ok", "isolation-ok\n", 0)

    monkeypatch.setattr("llm_benchmark.sandbox.command", info)
    sandbox = DockerSandbox()
    monkeypatch.setattr(sandbox, "_run", run)
    result = await sandbox.verify()
    assert result["available"] is available
    assert sandbox.verified is available
    if not available:
        with pytest.raises(IsolationUnavailable):
            await sandbox.execute("print('untrusted fixture')")


async def test_real_oom_verification_without_docker_oom_flag(monkeypatch):
    if os.environ.get("FORGE_TEST_DOCKER") != "1":
        pytest.skip("実Docker検証はFORGE_TEST_DOCKER=1で明示実行")
    import json

    async def without_flag(*args, **kwargs):
        rc, raw = await command(*args, **kwargs)
        if args[:3] == ("inspect", "--format", "{{json .State}}"):
            state = json.loads(raw)
            state["OOMKilled"] = False
            raw = json.dumps(state).encode()
        return rc, raw

    monkeypatch.setattr("llm_benchmark.sandbox.command", without_flag)
    sandbox = DockerSandbox()
    result = await sandbox.verify()
    assert result["available"], result["reason"]
