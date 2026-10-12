"""Disposable Docker workers. No bind mounts, secrets, host tools or model access."""

import asyncio
import json
import re
import uuid
from dataclasses import dataclass

IMAGE = "python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1"


class IsolationUnavailable(RuntimeError):
    pass


@dataclass
class CodeResult:
    status: str
    stdout: str
    exit_code: int | None


async def command(
    *args: str, input: bytes | None = None, timeout: float = 10, limit: int = 65536
) -> tuple[int, bytes]:
    proc = await asyncio.create_subprocess_exec(
        "docker",
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(timeout):
            assert proc.stdin and proc.stdout
            if input:
                proc.stdin.write(input)
                await proc.stdin.drain()
            proc.stdin.close()
            output = bytearray()
            while chunk := await proc.stdout.read(8192):
                output.extend(chunk)
                if len(output) > limit:
                    raise ValueError("output limit")
            return await proc.wait(), bytes(output)
    finally:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()


async def finish_creation(operation):
    # Docker may finish creating a container after its CLI client is cancelled.
    # Settle creation first; only then may the caller's finally remove the container.
    task = asyncio.create_task(operation)
    interrupted = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            interrupted = True
            if task.done():
                task.result()
                break
    if interrupted:
        raise asyncio.CancelledError
    return result


class DockerSandbox:
    def __init__(self, image: str = IMAGE):
        if not re.fullmatch(r"[a-zA-Z0-9_./:-]+@sha256:[a-f0-9]{64}", image):
            raise ValueError("隔離イメージはdigestで固定してください")
        self.image = image
        self.verified = False
        self.state = "unchecked"
        self.reason = "実隔離テストをまだ実行していません"

    async def _run(self, code: str, seconds: float = 5) -> CodeResult:
        name = "forge-worker-" + uuid.uuid4().hex
        try:
            rc, _ = await finish_creation(
                command(
                    "create",
                    "--pull",
                    "never",
                    "--name",
                    name,
                    "--label",
                    "benchmark-forge=disposable",
                    "-i",
                    "--network",
                    "none",
                    "--user",
                    "65534:65534",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--pids-limit",
                    "32",
                    "--memory",
                    "128m",
                    "--memory-swap",
                    "128m",
                    "--cpus",
                    "0.5",
                    "--ulimit",
                    "cpu=2:2",
                    "--ulimit",
                    "fsize=1048576:1048576",
                    "--ulimit",
                    "nofile=64:64",
                    "--tmpfs",
                    "/tmp:rw,nosuid,nodev,noexec,size=16m,mode=1777",
                    "--workdir",
                    "/tmp",
                    "--log-driver",
                    "none",
                    self.image,
                    "python",
                    "-I",
                    "-S",
                    "-",
                )
            )
            if rc:
                raise IsolationUnavailable(
                    "隔離コンテナを作成できません。Dockerと固定イメージを確認してください"
                )
            rc, raw = await command("inspect", name)
            inspection = json.loads(raw)[0]
            host = inspection["HostConfig"]
            if (
                inspection["Mounts"]
                or host["Privileged"]
                or host["NetworkMode"] != "none"
                or host["PidMode"] == "host"
                or not host["ReadonlyRootfs"]
                or inspection["Config"]["User"] != "65534:65534"
                or host["Memory"] != 134217728
                or host["PidsLimit"] != 32
                or host["CapDrop"] != ["ALL"]
            ):
                raise IsolationUnavailable("コンテナの実設定が制約と一致しません")
            try:
                rc, output = await command(
                    "start", "-a", "-i", name, input=code.encode(), timeout=seconds
                )
            except TimeoutError:
                return CodeResult("timeout", "", None)
            except ValueError:
                return CodeResult("output_limit", "", None)
            _, raw = await command("inspect", "--format", "{{json .State}}", name)
            state = json.loads(raw)
            return CodeResult(
                "oom" if state["OOMKilled"] else "ok" if rc == 0 else "error",
                output.decode("utf-8", errors="replace"),
                state["ExitCode"],
            )
        except (OSError, ValueError, KeyError, IndexError, TypeError, TimeoutError) as exc:
            raise IsolationUnavailable("Docker隔離の作成・監査に失敗しました") from exc
        finally:
            # Container deletion, not just killing the docker client, terminates descendants.
            cleanup = asyncio.create_task(command("rm", "-f", name, timeout=10))
            try:
                rc, _ = await asyncio.shield(cleanup)
                if rc != 0:
                    self.verified = False
                    raise IsolationUnavailable(
                        "隔離ワーカーの削除を確認できません。Dockerの状態を確認してください"
                    )
            except asyncio.CancelledError:
                await cleanup
                raise
            except (OSError, TimeoutError) as exc:
                self.verified = False
                raise IsolationUnavailable(
                    "隔離ワーカーの削除を確認できません。Dockerの状態を確認してください"
                ) from exc

    async def verify(self) -> dict:
        self.verified = False
        self.state = "unavailable"
        try:
            try:
                rc, raw = await command("info", "--format", "{{.OSType}}", timeout=5)
            except FileNotFoundError:
                self.state = "not_installed"
                raise IsolationUnavailable(
                    "Dockerが見つかりません。コード評価のみDocker Desktop（Linuxコンテナ）またはDocker Engineが必要です"
                ) from None
            except (OSError, TimeoutError, ValueError):
                self.state = "daemon_unavailable"
                raise IsolationUnavailable(
                    "Dockerに接続できません。Desktop/daemonの起動とアクセス権限を確認してください"
                ) from None
            if rc:
                self.state = "daemon_unavailable"
                raise IsolationUnavailable(
                    "Dockerに接続できません。Desktop/daemonの起動とアクセス権限を確認してください"
                )
            if raw.strip() != b"linux":
                self.state = "unsupported_engine"
                raise IsolationUnavailable(
                    "Linuxコンテナに切り替えてください。Windowsコンテナでのコード評価は無効です"
                )
            self.state = "verification_failed"

            # All code here is a fixed diagnostic fixture. No user/model code before validation.
            result = await self._run("""import os,socket,resource,json
assert os.getuid() == 65534
status=open('/proc/self/status').read()
assert 'NoNewPrivs:\\t1' in status
assert 'CapEff:\\t0000000000000000' in status
assert 'Seccomp:\\t2' in status
for path in ['/root/.ssh/id_rsa','/var/run/docker.sock','/workspace/benchmark-forge/.git/config']:
    assert not os.path.exists(path)
try:
    open('/forbidden-write','w').write('x')
    raise AssertionError('writable root')
except OSError: pass
open('/tmp/permitted','w').write('ok')
try:
    socket.create_connection(('1.1.1.1',443),timeout=.5)
    raise AssertionError('network enabled')
except OSError: pass
assert resource.getrlimit(resource.RLIMIT_CPU)[0] == 2
assert resource.getrlimit(resource.RLIMIT_FSIZE)[0] == 1048576
assert open('/sys/fs/cgroup/memory.max').read().strip() == '134217728'
assert open('/sys/fs/cgroup/pids.max').read().strip() == '32'
assert open('/sys/fs/cgroup/cpu.max').read().split()[0] == '50000'
print('isolation-ok')
""")
            if result.status != "ok" or result.stdout.strip() != "isolation-ok":
                raise IsolationUnavailable(
                    "無権限・通信・ファイル・cgroup制限の実検証に失敗しました"
                )
            oom = await self._run("x=bytearray(300*1024*1024)")
            timeout = await self._run("while True: pass", seconds=6)
            if oom.status != "oom" or timeout.status not in {"error", "timeout"}:
                raise IsolationUnavailable("OOM/CPU時間制限の実検証に失敗しました")
            self.verified = True
            self.state = "verified"
            self.reason = "non-root、通信禁止、read-only、cgroup制限、OOM、時間制限を実検証済み"
        except IsolationUnavailable as exc:
            self.reason = str(exc)
        return {
            "available": self.verified,
            "state": self.state,
            "reason": self.reason,
            "image": self.image,
        }

    async def execute(self, code: str, seconds: float = 5) -> CodeResult:
        if not self.verified:
            raise IsolationUnavailable(self.reason)
        if len(code.encode()) > 64000 or not 0 < seconds <= 10:
            raise ValueError("コードサイズまたは実行時間が範囲外です")
        try:
            return await self._run(code, seconds)
        except IsolationUnavailable as exc:
            self.verified = False
            self.state = "verification_failed"
            self.reason = str(exc)
            raise


def sandbox_status() -> dict:
    return {
        "available": False,
        "code_execution": False,
        "agent_execution": False,
        "reason": "Docker使い捨てワーカーを実装。実行プロセスごとの隔離検証が必要です。Codex liveは未検証で無効。",
        "text_code_reading": True,
        "text_tool_selection": True,
        "native_tools": False,
        "multi_turn_agents": False,
    }


def execute_code(code: str) -> None:
    raise IsolationUnavailable(
        "同期のホスト実行は禁止。検証済みDockerSandbox.executeを使用してください"
    )
