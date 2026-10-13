"""Non-secret, process-cached hardware inventory. No usage or power estimates."""

import csv
import json
import math
import os
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
    devices, reason = nvidia_inventory()
    result.update(gpu_devices=devices or None, gpu_inventory_reason=reason)
    if platform.system() == "Windows":
        windows_devices, windows_reason = windows_gpu_inventory()
        names = {device["name"].casefold() for device in devices}
        devices.extend(
            device for device in windows_devices if device["name"].casefold() not in names
        )
        result["gpu_devices"] = devices or None
        result["gpu_inventory_reason"] = (
            "; ".join(message for message in (reason, windows_reason) if message) or None
        )
    return result


def nvidia_binary() -> str | None:
    binary = shutil.which("nvidia-smi")
    if binary or platform.system() != "Windows":
        return binary
    # Drivers can install nvidia-smi without adding NVSMI to PATH.
    candidates = [
        Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "nvidia-smi.exe",
        Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        / "NVIDIA Corporation"
        / "NVSMI"
        / "nvidia-smi.exe",
    ]
    return next((str(path) for path in candidates if path.is_file()), None)


def nvidia_inventory() -> tuple[list[dict], str | None]:
    binary = nvidia_binary()
    if not binary:
        return [], "nvidia-smiが見つかりません（NVIDIAの詳細は未取得）"
    timeout = 8 if platform.system() == "Windows" else 2
    try:
        process = subprocess.run(
            [
                binary,
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8-sig",
            timeout=timeout,
            check=True,
        )
        if len(process.stdout) > 64000:
            raise ValueError("inventory limit")
        devices = []
        for row in csv.reader(process.stdout.splitlines()):
            if len(row) != 3 or not row[0].strip() or not row[1].strip():
                raise ValueError("invalid inventory")
            memory_text = row[2].strip()
            memory = (
                None if memory_text in {"N/A", "[N/A]", "[Not Supported]"} else int(memory_text)
            )
            if memory is not None and memory <= 0:
                raise ValueError("invalid memory")
            devices.append(
                {
                    "name": row[0].strip(),
                    "driver_version": row[1].strip(),
                    "total_vram_bytes": memory * 1048576 if memory is not None else None,
                    "source": "nvidia-smi",
                    "memory_unavailable_reason": "ドライバーがVRAM容量を報告していません"
                    if memory is None
                    else None,
                }
            )
        if not devices:
            raise ValueError("no devices")
        return devices, None
    except subprocess.TimeoutExpired:
        return [], f"nvidia-smiが{timeout}秒以内に応答しません（GPU詳細は未取得）"
    except subprocess.CalledProcessError:
        return [], "nvidia-smiが失敗しました。NVIDIAドライバーの状態を確認してください"
    except OSError:
        return [], "nvidia-smiを起動できません（実行パス・権限を確認してください）"
    except ValueError:
        return [], "nvidia-smiの応答形式を読み取れません（GPU詳細は未取得）"


def windows_gpu_inventory() -> tuple[list[dict], str | None]:
    """CIM adapter names only. AdapterRAM is not a reliable dedicated VRAM capacity."""
    binary = (
        Path(os.environ.get("SystemRoot", "C:/Windows"))
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    command = (
        "$ErrorActionPreference='Stop'; "
        "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
        "@(Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion) "
        "| ConvertTo-Json -Compress"
    )
    try:
        process = subprocess.run(
            [str(binary), "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8-sig",
            timeout=8,
            check=True,
        )
        if len(process.stdout) > 64000:
            raise ValueError("inventory limit")
        rows = json.loads(process.stdout)
        # PowerShell 5.1 may unwrap a one-element pipeline array.
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list) or not rows:
            raise ValueError("no adapters")
        devices = []
        for row in rows:
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("Name"), str)
                or not row["Name"].strip()
            ):
                raise ValueError("invalid adapter")
            driver = row.get("DriverVersion")
            devices.append(
                {
                    "name": row["Name"].strip(),
                    "driver_version": driver
                    if isinstance(driver, str) and driver.strip()
                    else None,
                    "total_vram_bytes": None,
                    "source": "windows-cim",
                    "memory_unavailable_reason": "CIMの共有/専用メモリをVRAM容量の代用にはしません",
                }
            )
        return devices, None
    except subprocess.TimeoutExpired:
        return [], "Windows GPU構成の取得が8秒でタイムアウトしました"
    except (OSError, subprocess.SubprocessError, ValueError):
        return [], "Windows GPU構成を取得できません（CIM/PowerShell）"


def backend_versions() -> dict:
    values: dict[str, str | None] = {}
    for name in ["benchmark-forge", "httpx", "torch", "transformers"]:
        try:
            values[name] = version(name)
        except PackageNotFoundError:
            values[name] = None
    return values


def torch_status() -> dict:
    """Explicit probe in a short-lived interpreter; base startup never imports Torch."""
    import json
    import sys

    from llm_benchmark.platform_support import worker_environment

    try:
        result = subprocess.run(
            [sys.executable, "-m", "llm_benchmark.torch_probe"],
            env=worker_environment(),
            capture_output=True,
            timeout=20,
            check=True,
        )
        if len(result.stdout) > 64000:
            raise ValueError("probe output limit")
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return {
            "available": False,
            "cuda_available": None,
            "live_model_verified": False,
            "reason": "PyTorchを読み込めません。任意依存・DLL・ドライバーを確認してください（通常評価は利用可能）",
        }


def gpu_status() -> dict:
    """Explicit point sample of device-wide counters, never a model-specific peak."""
    from datetime import UTC, datetime

    result: dict[str, Any] = {
        "available": False,
        "scope": "GPU全体の単発計測。他アプリも含み、モデル専用の使用量やPeakではありません",
        "devices": None,
        "observed_at": None,
        "reason": None,
    }
    binary = nvidia_binary()
    if not binary:
        return {**result, "reason": "nvidia-smiが見つかりません。GPUの単発計測は利用不可です"}
    try:
        process = subprocess.run(
            [
                binary,
                "--query-gpu=uuid,name,utilization.gpu,memory.used,power.draw,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8-sig",
            timeout=8,
            check=True,
        )
        devices = parse_gpu_sample(process.stdout)
        return {
            **result,
            "available": True,
            "devices": devices,
            "observed_at": datetime.now(UTC).isoformat(),
        }
    except subprocess.TimeoutExpired:
        result["reason"] = "nvidia-smiの単発計測が8秒でタイムアウトしました"
    except (OSError, subprocess.SubprocessError, ValueError):
        result["reason"] = "nvidia-smiの単発計測に失敗しました（ドライバーまたは応答形式）"
    return result


def parse_gpu_sample(stdout: str) -> list[dict]:
    if len(stdout) > 64000:
        raise ValueError("sample limit")
    devices = []
    for row in csv.reader(stdout.splitlines()):
        if len(row) != 6 or not row[0].strip() or not row[1].strip():
            raise ValueError("invalid sample")
        values: dict[str, float | None] = {}
        reasons = {}
        for key, raw, limit, scale in zip(
            ("utilization_percent", "used_vram_bytes", "power_watts", "temperature_celsius"),
            row[2:],
            (100, None, None, None),
            (1, 1048576, 1, 1),
            strict=True,
        ):
            raw = raw.strip()
            if raw in {"N/A", "[N/A]", "[Not Supported]"}:
                values[key] = None
                reasons[key] = "ドライバーがこの計測値を提供していません"
                continue
            value = float(raw)
            if not math.isfinite(value) or value < 0 or (limit is not None and value > limit):
                raise ValueError("invalid sample value")
            values[key] = value * scale
        devices.append(
            {
                "uuid": row[0].strip(),
                "name": row[1].strip(),
                **values,
                "unavailable_reasons": reasons,
            }
        )
    if not devices:
        raise ValueError("no sample")
    return devices
