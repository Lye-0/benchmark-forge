"""Non-secret, process-cached hardware inventory. No usage or power estimates."""

import csv
import platform
import shutil
import subprocess
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import psutil


@lru_cache(maxsize=1)
def hardware_inventory() -> dict:
    cpu = platform.processor() or platform.machine()
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    result: dict[str, Any] = {
        "cpu_model": cpu,
        "logical_cpus": psutil.cpu_count(),
        "physical_cpus": psutil.cpu_count(logical=False),
        "system_ram_total_bytes": psutil.virtual_memory().total,
        "gpu_devices": None,
        "gpu_inventory_reason": "nvidia-smiが見つかりません",
        "inventory_scope": "application host; first-use cached hardware inventory; not sampled usage",
    }
    binary = shutil.which("nvidia-smi")
    if not binary:
        return result
    try:
        process = subprocess.run(
            [
                binary,
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        )
        if len(process.stdout) > 64000:
            raise ValueError("inventory limit")
        devices = []
        for row in csv.reader(process.stdout.splitlines()):
            if len(row) != 3:
                raise ValueError("invalid inventory")
            memory = int(row[2].strip())
            if memory <= 0:
                raise ValueError("invalid memory")
            devices.append(
                {
                    "name": row[0].strip(),
                    "driver_version": row[1].strip(),
                    "total_vram_bytes": memory * 1048576,
                }
            )
        if not devices:
            raise ValueError("no devices")
        result.update(gpu_devices=devices, gpu_inventory_reason=None)
    except (OSError, subprocess.SubprocessError, ValueError):
        result["gpu_inventory_reason"] = (
            "GPU情報を取得できません（使用率・電力の代用値は生成しません）"
        )
    return result


def backend_versions() -> dict:
    values: dict[str, str | None] = {}
    for name in ["benchmark-forge", "httpx", "torch", "transformers"]:
        try:
            values[name] = version(name)
        except PackageNotFoundError:
            values[name] = None
    return values
