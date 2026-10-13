"""Optional bounded-memory host GPU sampling; never model-specific allocation."""

import asyncio
import time
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from llm_benchmark.environment import nvidia_binary, parse_gpu_sample

FIELDS = ("utilization_percent", "used_vram_bytes", "power_watts", "temperature_celsius")
SCOPE = "評価中のアプリ実行ホストのGPU全体。他アプリの負荷も含みます。値は離散サンプルの平均・観測最大値で、モデル専用のPeak・時間加重平均・消費電力量ではありません。短い処理やサンプル間のピークは取得できません。"


async def sample_devices(binary: str) -> list[dict]:
    creation = asyncio.create_task(
        asyncio.create_subprocess_exec(
            binary,
            "--query-gpu=uuid,name,utilization.gpu,memory.used,power.draw,temperature.gpu",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    )
    process = None
    try:
        try:
            process = await asyncio.shield(creation)
        except asyncio.CancelledError:
            process = await creation
            raise
        async with asyncio.timeout(2):
            stdout, _ = await process.communicate()
        if process.returncode:
            raise ValueError("GPU probe failed")
        return parse_gpu_sample(stdout.decode("utf-8-sig"))
    finally:
        if process is not None and process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()


class GpuSampler:
    def __init__(self, enabled: bool, interval: float = 1):
        self.enabled = enabled
        self.interval = interval
        self.task: asyncio.Task | None = None
        self.devices: dict[str, dict[str, Any]] = {}
        self.samples = 0
        self.failures = 0
        self.reason: str | None = None
        self.first_at: str | None = None
        self.last_at: str | None = None
        self.started = 0.0
        self.elapsed = 0.0

    def start(self):
        if self.enabled:
            self.started = time.perf_counter()
            self.task = asyncio.create_task(self.collect())

    async def collect(self):
        binary = nvidia_binary()
        if not binary:
            self.reason = "nvidia-smiが見つかりません。評価は計測なしで継続します"
            return
        while True:
            started = time.perf_counter()
            try:
                devices = await sample_devices(binary)
                self.samples += 1
                self.last_at = datetime.now(UTC).isoformat()
                self.first_at = self.first_at or self.last_at
                for device in devices:
                    record = self.devices.setdefault(
                        device["uuid"],
                        {
                            "uuid": device["uuid"],
                            "name": device["name"],
                            "metrics": {},
                            "unavailable_reasons": {},
                        },
                    )
                    record["unavailable_reasons"].update(device.get("unavailable_reasons", {}))
                    for key in FIELDS:
                        value = device[key]
                        stat = record["metrics"].setdefault(
                            key, {"count": 0, "sum": 0.0, "observed_max": None}
                        )
                        if value is not None:
                            stat["count"] += 1
                            stat["sum"] += value
                            previous = stat["observed_max"]
                            stat["observed_max"] = (
                                value if previous is None else max(previous, value)
                            )
            except (OSError, ValueError, TimeoutError):
                self.failures += 1
                self.reason = (
                    "GPU計測に欠測があります（応答失敗・形式不明・2秒の取得期限）。評価は継続します"
                )
                # Avoid continuously probing a failing driver for hours.
                if self.failures >= 3:
                    return
            await asyncio.sleep(max(0, self.interval - (time.perf_counter() - started)))

    async def close(self):
        if self.task:
            self.elapsed = time.perf_counter() - self.started
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task

    def summary(self) -> dict:
        devices = []
        for record in self.devices.values():
            devices.append(
                {
                    **record,
                    "metrics": {
                        key: {
                            "samples": stat["count"],
                            "mean": stat["sum"] / stat["count"] if stat["count"] else None,
                            "observed_max": stat["observed_max"],
                        }
                        for key, stat in record["metrics"].items()
                    },
                }
            )
        return {
            "scope": SCOPE,
            "interval_seconds": self.interval,
            "window_seconds": self.elapsed,
            "samples": self.samples,
            "failed_samples": self.failures,
            "first_observed_at": self.first_at,
            "last_observed_at": self.last_at,
            "reason": self.reason
            or ("処理中に完了したサンプルがありません" if not self.samples else None),
            "devices": devices,
        }


def summarize_gpu(results: list) -> dict | None:
    windows = [r.metrics["gpu_sampling"] for r in results if "gpu_sampling" in r.metrics]
    if not windows:
        return None
    devices: dict[str, dict] = {}
    for window in windows:
        for device in window["devices"]:
            target = devices.setdefault(
                device["uuid"], {"uuid": device["uuid"], "name": device["name"], "metrics": {}}
            )
            target.setdefault("unavailable_reasons", {}).update(
                device.get("unavailable_reasons", {})
            )
            for key, value in device["metrics"].items():
                stat = target["metrics"].setdefault(
                    key, {"samples": 0, "sum": 0.0, "observed_max": None}
                )
                if value["samples"]:
                    stat["samples"] += value["samples"]
                    stat["sum"] += value["mean"] * value["samples"]
                    previous = stat["observed_max"]
                    stat["observed_max"] = (
                        value["observed_max"]
                        if previous is None
                        else max(previous, value["observed_max"])
                    )
    for device in devices.values():
        for value in device["metrics"].values():
            value["mean"] = value.pop("sum") / value["samples"] if value["samples"] else None
            value.pop("sum", None)
    return {
        "scope": SCOPE,
        "result_windows": len(windows),
        "windows_without_samples": sum(w["samples"] == 0 for w in windows),
        "samples": sum(w["samples"] for w in windows),
        "failed_samples": sum(w["failed_samples"] for w in windows),
        "devices": list(devices.values()),
    }
