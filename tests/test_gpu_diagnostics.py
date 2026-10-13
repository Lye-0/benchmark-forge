import json
import subprocess
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from llm_benchmark import environment as env
from llm_benchmark.cli import app


@pytest.fixture(autouse=True)
def clear_inventory_cache():
    env.hardware_inventory.cache_clear()
    yield
    env.hardware_inventory.cache_clear()


@pytest.mark.parametrize("nvidia", ["valid", "timeout", "unavailable-memory"])
def test_windows_hybrid_inventory_keeps_both_adapters(monkeypatch, nvidia):
    monkeypatch.setattr(env.platform, "processor", lambda: "Fixture CPU")
    monkeypatch.setattr(env.platform, "system", lambda: "Windows")
    monkeypatch.setattr(env.shutil, "which", lambda _: "nvidia-smi.exe")
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        assert kwargs["timeout"] == 8
        assert kwargs["encoding"] == "utf-8-sig"
        assert "shell" not in kwargs
        if args[0] == "nvidia-smi.exe":
            if nvidia == "timeout":
                raise subprocess.TimeoutExpired(args, 8)
            return SimpleNamespace(
                stdout="NVIDIA GeForce RTX 5070 Laptop GPU, 999.00, "
                + ("8192" if nvidia == "valid" else "[N/A]")
                + "\n"
            )
        assert "-NoProfile" in args and "-NonInteractive" in args
        assert "AdapterRAM" not in args[-1]
        return SimpleNamespace(
            stdout=json.dumps(
                [
                    {"Name": "Intel(R) UHD Graphics", "DriverVersion": "fixture-intel"},
                    {
                        "Name": "NVIDIA GeForce RTX 5070 Laptop GPU",
                        "DriverVersion": "fixture-nvidia",
                    },
                ]
            )
        )

    monkeypatch.setattr(env.subprocess, "run", run)
    result = env.hardware_inventory()
    assert len(result["gpu_devices"]) == 2
    assert env.hardware_inventory() is result
    assert len(calls) == 2
    devices = {d["name"]: d for d in result["gpu_devices"]}
    assert devices["Intel(R) UHD Graphics"]["total_vram_bytes"] is None
    gpu = devices["NVIDIA GeForce RTX 5070 Laptop GPU"]
    if nvidia == "valid":
        assert gpu["source"] == "nvidia-smi"
        assert gpu["total_vram_bytes"] == 8192 * 1048576
        assert result["gpu_inventory_reason"] is None
    elif nvidia == "timeout":
        assert gpu["source"] == "windows-cim"
        assert "8秒" in result["gpu_inventory_reason"]
        assert gpu["total_vram_bytes"] is None
    else:
        assert gpu["total_vram_bytes"] is None
        assert gpu["memory_unavailable_reason"]


def test_windows_driver_binary_without_path(monkeypatch, tmp_path):
    monkeypatch.setattr(env.platform, "processor", lambda: "Fixture CPU")
    monkeypatch.setattr(env.platform, "system", lambda: "Windows")
    monkeypatch.setattr(env.shutil, "which", lambda _: None)
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    binary = tmp_path / "System32" / "nvidia-smi.exe"
    binary.parent.mkdir()
    binary.touch()
    assert env.nvidia_binary() == str(binary)


@pytest.mark.parametrize(
    "stdout",
    [
        '{"Name":"表示アダプター","DriverVersion":null}',
        '[{"Name":"表示アダプター","DriverVersion":"1.0"}]',
    ],
)
def test_cim_single_adapter_and_unicode(monkeypatch, stdout):
    monkeypatch.setattr(env.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=stdout))
    devices, reason = env.windows_gpu_inventory()
    assert reason is None
    assert devices[0]["name"] == "表示アダプター"
    assert devices[0]["total_vram_bytes"] is None


@pytest.mark.parametrize("stdout", ["null", "[]", "[{}]", "broken"])
def test_cim_failure_is_optional(monkeypatch, stdout):
    monkeypatch.setattr(env.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=stdout))
    devices, reason = env.windows_gpu_inventory()
    assert not devices and reason


@pytest.mark.parametrize("power", ["25.5", "[Not Supported]"])
def test_device_sample_preserves_zero_and_unknown(monkeypatch, power):
    monkeypatch.setattr(env, "nvidia_binary", lambda: "fixture")
    monkeypatch.setattr(
        env.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout=f"GPU-fixture, RTX fixture, 0, 1200, {power}, 42\n"),
    )
    result = env.gpu_status()
    assert result["available"] and result["observed_at"]
    device = result["devices"][0]
    assert device["utilization_percent"] == 0
    assert device["used_vram_bytes"] == 1200 * 1048576
    assert device["power_watts"] == (25.5 if power == "25.5" else None)
    assert "Peakではありません" in result["scope"]
    if power != "25.5":
        assert device["unavailable_reasons"]["power_watts"]


@pytest.mark.parametrize("usage", ["NaN", "inf", "-1", "101"])
def test_invalid_sample_is_not_reported_as_measurement(monkeypatch, usage):
    monkeypatch.setattr(env, "nvidia_binary", lambda: "fixture")
    monkeypatch.setattr(
        env.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            stdout=f"GPU-fixture, RTX fixture, {usage}, 1200, 25, 42\n"
        ),
    )
    result = env.gpu_status()
    assert not result["available"]
    assert result["devices"] is None and result["reason"]


def test_doctor_gpu_is_opt_in_and_does_not_require_torch(monkeypatch):
    monkeypatch.setattr(env, "hardware_inventory", lambda: {"gpu_inventory_reason": "診断fixture"})
    monkeypatch.setattr(env, "backend_versions", lambda: {})
    calls = []
    monkeypatch.setattr(env, "gpu_status", lambda: calls.append(True) or {"available": False})
    runner = CliRunner()
    assert runner.invoke(app, ["doctor"]).exit_code == 0
    assert not calls
    result = runner.invoke(app, ["doctor", "--gpu"])
    assert result.exit_code == 0
    assert result.stdout.isascii()
    assert json.loads(result.stdout)["gpu_inventory_reason"] == "診断fixture"
    assert json.loads(result.stdout)["gpu_sample"]["available"] is False
    assert calls == [True]


def test_gpu_api_is_explicit_and_remains_optional(store, monkeypatch):
    from fastapi.testclient import TestClient

    from llm_benchmark.api import create_app

    calls = []
    monkeypatch.setattr(
        "llm_benchmark.api.gpu_status",
        lambda: calls.append(True) or {"available": False, "reason": "fixture unavailable"},
    )
    with TestClient(create_app(store.path.parent), base_url="http://127.0.0.1") as client:
        assert not calls
        response = client.post("/api/environment/gpu", json={})
        assert response.status_code == 200
        assert response.json()["available"] is False
        assert calls == [True]
