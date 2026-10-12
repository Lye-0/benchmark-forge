"""Disposable process boundary: cancellation kills and reaps the inference worker."""

import asyncio
import importlib.util
import json
import os
import signal
import sys
from contextlib import suppress
from pathlib import Path

from llm_benchmark.domain import ModelConfig, PublicProblem, Response


def readiness(config: ModelConfig) -> str | None:
    if sys.platform != "linux":
        return "TransformersワーカーはLinux / WSL2のみ対応しています"
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
        from llm_benchmark.adapters import AdapterError

        # No inherited credentials, proxy, Python injection variables or automatic downloads.
        env = {
            "PATH": os.defpath,
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "TOKENIZERS_PARALLELISM": "false",
        }
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "llm_benchmark.transformers_worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        try:
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
            raise AdapterError(
                "Transformers推論失敗。依存・モデル形式・コンテキスト長・デバイスを確認してください"
            ) from exc
        finally:
            # Also remove descendants if the process leader already exited.
            with suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            await proc.wait()
