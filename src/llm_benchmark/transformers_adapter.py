"""Disposable process boundary: cancellation kills and reaps the inference worker."""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

from llm_benchmark.domain import ModelConfig, PublicProblem, Response
from llm_benchmark.platform_support import terminate_worker, worker_environment


def readiness(config: ModelConfig) -> str | None:
    if sys.platform not in {"linux", "win32"}:
        return "TransformersワーカーはWindows / Linux / WSL2に対応しています"
    if config.quantization not in {"N/A", "none"}:
        return "Transformersの量子化指定は未対応です。N/Aまたはnoneを指定してください"
    if not Path(config.model).is_dir():
        return "Transformersには取得済みモデルのローカルディレクトリを指定してください"
    if any(importlib.util.find_spec(name) is None for name in ("torch", "transformers")):
        return "任意依存transformersが未導入です（uv sync --extra transformers）"
    return None


class TransformersAdapter:
    def __init__(self, config: ModelConfig):
        self.config = config

    async def complete(self, problem: PublicProblem) -> Response:
        from llm_benchmark.adapters import ExecutionUnavailable

        # No inherited credentials, proxy, Python injection variables or automatic downloads.
        env = worker_environment()
        proc = None
        job = None
        try:
            creation = asyncio.create_task(
                asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "llm_benchmark.transformers_worker",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    env=env,
                    start_new_session=sys.platform != "win32",
                )
            )
            try:
                proc = await asyncio.shield(creation)
            except asyncio.CancelledError:
                # A process can appear after cancellation of its creation await.
                # Settle creation and reap it before propagating the cancellation.
                proc = await creation
                raise
            if sys.platform == "win32":
                from llm_benchmark.windows_job import WindowsJob

                job = WindowsJob(proc.pid)
            assert proc.stdin is not None and proc.stdout is not None
            payload = json.dumps(
                {"config": self.config.model_dump(), "problem": problem.model_dump()}
            )
            async with asyncio.timeout(self.config.timeout_seconds):
                proc.stdin.write(payload.encode())
                await proc.stdin.drain()
                proc.stdin.close()
                chunks = bytearray()
                while chunk := await proc.stdout.read(65536):
                    chunks.extend(chunk)
                    if len(chunks) > 1_000_000:
                        raise ValueError("Worker output exceeds limit")
                await proc.wait()
                if proc.returncode != 0:
                    raise ValueError("Worker failed")
                return Response.model_validate_json(bytes(chunks))
        except TimeoutError:
            raise
        except (ValueError, OSError) as exc:
            raise ExecutionUnavailable(
                "Transformers推論失敗。依存・モデル形式・コンテキスト長・デバイスを確認してください"
            ) from exc
        finally:
            if proc is not None:
                terminate_worker(proc, job)
                await proc.wait()
