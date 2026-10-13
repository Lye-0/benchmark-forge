import asyncio
from types import SimpleNamespace

import pytest

from llm_benchmark import gpu_sampling as gpu
from llm_benchmark.domain import ModelConfig, SetConfig
from llm_benchmark.runner import Scheduler, summarize
from llm_benchmark.sets import build_set


def sample(value):
    return [
        {
            "uuid": "GPU-fixture",
            "name": "fixture",
            "utilization_percent": value,
            "used_vram_bytes": value * 1024,
            "power_watts": None,
            "temperature_celsius": 40,
        }
    ]


async def test_sampler_aggregates_without_retaining_raw_samples(monkeypatch):
    monkeypatch.setattr(gpu, "nvidia_binary", lambda: "fixture")
    ready = asyncio.Event()
    calls = 0

    async def probe(binary):
        nonlocal calls
        calls += 1
        if calls == 3:
            ready.set()
            await asyncio.Event().wait()
        return sample(0 if calls == 1 else 100)

    monkeypatch.setattr(gpu, "sample_devices", probe)
    sampler = gpu.GpuSampler(True, interval=0.001)
    sampler.start()
    await asyncio.wait_for(ready.wait(), 1)
    await sampler.close()
    report = sampler.summary()
    assert report["samples"] == 2
    stats = report["devices"][0]["metrics"]
    assert stats["utilization_percent"] == {"samples": 2, "mean": 50, "observed_max": 100}
    assert stats["power_watts"] == {"samples": 0, "mean": None, "observed_max": None}
    assert report["first_observed_at"] and report["last_observed_at"]
    assert sampler.task.done()
    overall = gpu.summarize_gpu([SimpleNamespace(metrics={"gpu_sampling": report})] * 2)
    assert overall["devices"][0]["metrics"]["utilization_percent"]["samples"] == 4
    assert overall["devices"][0]["metrics"]["utilization_percent"]["mean"] == 50


async def test_missing_gpu_and_repeated_failures_remain_optional(monkeypatch):
    monkeypatch.setattr(gpu, "nvidia_binary", lambda: None)
    sampler = gpu.GpuSampler(True)
    sampler.start()
    await sampler.task
    await sampler.close()
    assert sampler.summary()["samples"] == 0
    assert sampler.summary()["reason"]
    monkeypatch.setattr(gpu, "nvidia_binary", lambda: "fixture")

    async def failed(binary):
        raise TimeoutError

    monkeypatch.setattr(gpu, "sample_devices", failed)
    sampler = gpu.GpuSampler(True, interval=0.001)
    sampler.start()
    await asyncio.wait_for(sampler.task, 1)
    await sampler.close()
    assert sampler.summary()["failed_samples"] == 3


async def test_cancel_probe_kills_and_reaps_process(monkeypatch):
    entered = asyncio.Event()

    class Process:
        returncode = None
        killed = waited = False

        async def communicate(self):
            entered.set()
            await asyncio.Event().wait()

        def kill(self):
            self.killed = True
            self.returncode = -9

        async def wait(self):
            self.waited = True

    process = Process()

    async def create(*args, **kwargs):
        assert kwargs["stderr"] == asyncio.subprocess.DEVNULL
        return process

    monkeypatch.setattr(gpu.asyncio, "create_subprocess_exec", create)
    task = asyncio.create_task(gpu.sample_devices("fixture"))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.killed and process.waited


@pytest.mark.parametrize("behavior", ["reference", "timeout", "error"])
async def test_sampler_persists_on_success_failure_and_timeout(store, monkeypatch, behavior):
    monkeypatch.setattr(gpu, "nvidia_binary", lambda: "fixture")

    async def probe(binary):
        return sample(30)

    monkeypatch.setattr(gpu, "sample_devices", probe)
    model = ModelConfig(
        model_id="sampled",
        name="sampled",
        backend="mock",
        gpu_sampling=True,
        mock_behavior=behavior,
        timeout_seconds=0.1,
    )
    store.save_model(model)
    frozen = build_set(SetConfig(generator_ids=["math.linear"], count=1))
    store.save_set(frozen)
    scheduler = Scheduler(store)
    scheduler.start()
    try:
        id = scheduler.create(frozen.set_id, [model.model_id])[0]
        await scheduler.queue.join()
        report = summarize(store, id)
        assert report["status"] == "completed"
        window = report["results"][0]["metrics"]["gpu_sampling"]
        assert window["samples"] == 1
        assert report["resources"]["gpu_sampling"]["samples"] == 1
        assert (
            report["results"][0]["status"]
            == {"reference": "correct", "timeout": "timeout", "error": "error"}[behavior]
        )
        assert store.attempts(id)[0]["data"]["metrics"]["gpu_sampling"] == window
    finally:
        await scheduler.close()


async def test_disabled_sampler_never_probes(monkeypatch):
    def unexpected():
        raise AssertionError("disabled GPU sampling")

    monkeypatch.setattr(gpu, "nvidia_binary", unexpected)
    sampler = gpu.GpuSampler(False)
    sampler.start()
    await sampler.close()
    assert sampler.task is None


async def test_cancel_during_probe_creation_waits_for_process_and_reaps_it(monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    class Process:
        returncode = None
        killed = waited = False

        def kill(self):
            self.killed = True
            self.returncode = -9

        async def wait(self):
            self.waited = True

    process = Process()

    async def delayed(*args, **kwargs):
        entered.set()
        await release.wait()
        return process

    monkeypatch.setattr(gpu.asyncio, "create_subprocess_exec", delayed)
    task = asyncio.create_task(gpu.sample_devices("fixture"))
    await entered.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.killed and process.waited
