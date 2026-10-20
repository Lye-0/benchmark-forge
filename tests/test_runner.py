import asyncio
import time

import pytest

from llm_benchmark.domain import ModelConfig, Result
from llm_benchmark.runner import Scheduler, comparison, summarize


async def wait_until(condition, seconds=3):
    async with asyncio.timeout(seconds):
        while not condition():
            await asyncio.sleep(0.005)


async def test_shared_set_scoring_and_no_duplicates(store, frozen):
    scheduler = Scheduler(store)
    scheduler.start()
    try:
        ids = scheduler.create(frozen.set_id, ["mock-reference", "mock-wrong"])
        await scheduler.queue.join()
        reports = [summarize(store, id) for id in ids]
        assert reports[0]["completed"] == 20
        assert reports[0]["accuracy"] == pytest.approx(1)
        assert reports[1]["accuracy"] == 0
        assert reports[0]["set_hash"] == reports[1]["set_hash"]
        for report in reports:
            assert report["accuracy"] == pytest.approx(
                sum(group["weighted_contribution"] for group in report["by_origin"].values())
            )
            assert report["accuracy"] == pytest.approx(
                sum(group["weighted_contribution"] for group in report["by_category"].values())
            )
            assert len({r["problem_id"] for r in report["results"]}) == 20
            assert report["environment"]["peak_vram_bytes"] is None
            assert report["latency_p50"] > 0
        result = comparison(reports)
        assert result["comparable"]
        assert any("Mock" in w for w in result["warnings"])
    finally:
        await scheduler.close()


async def test_pause_restart_resume_persistence(store, frozen):
    scheduler = Scheduler(store)
    scheduler.start()
    id = scheduler.create(frozen.set_id, ["mock-reference"])[0]
    await wait_until(lambda: len(store.run(id)["results"]) >= 2)
    scheduler.control(id, "pause")
    await scheduler.queue.join()
    assert store.run(id)["status"] == "paused"
    count = len(store.run(id)["results"])
    assert 2 <= count < 20
    await scheduler.close()
    # New worker, same retained database, no live process assumptions.
    scheduler = Scheduler(store)
    scheduler.start()
    try:
        scheduler.control(id, "resume")
        await scheduler.queue.join()
        report = summarize(store, id)
        assert report["status"] == "completed"
        assert report["completed"] == 20
        assert report["correct"] == 20
        assert len({r["index"] for r in report["results"]}) == 20
        with pytest.raises(ValueError):
            scheduler.control(id, "resume")
    finally:
        await scheduler.close()


async def test_abrupt_worker_shutdown_restores_and_lock(store, frozen):
    scheduler = Scheduler(store)
    scheduler.start()
    id = scheduler.create(frozen.set_id, ["mock-reference"])[0]
    other = Scheduler(store)
    with pytest.raises(RuntimeError, match="別の評価"):
        other.start()
    await wait_until(lambda: len(store.run(id)["results"]) >= 1)
    await scheduler.close()
    assert store.run(id)["status"] == "paused"
    other.start()
    try:
        other.control(id, "resume")
        await other.queue.join()
        assert summarize(store, id)["correct"] == 20
    finally:
        await other.close()


@pytest.mark.parametrize(
    "behavior,outcome", [("timeout", "timeout"), ("error", "error"), ("empty", "empty")]
)
async def test_errors_are_in_denominator_and_retry(store, frozen, behavior, outcome):
    model = ModelConfig(
        model_id="test-failure",
        name="Fail test",
        backend="mock",
        mock_behavior=behavior,
        timeout_seconds=0.1,
    )
    store.save_model(model)
    scheduler = Scheduler(store)
    scheduler.start()
    try:
        id = scheduler.create(frozen.set_id, [model.model_id])[0]
        await scheduler.queue.join()
        report = summarize(store, id)
        assert report["status_counts"][outcome] == 20
        assert report["total"] == 20
        assert report["accuracy"] == 0
        assert report["completion_rate"] == 0
        if behavior != "empty":
            scheduler.control(id, "retry")
            await scheduler.queue.join()
            assert len(store.run(id)["results"]) == 20
    finally:
        await scheduler.close()


async def test_cancel_late_answer_and_sequential_queue(store, frozen):
    scheduler = Scheduler(store)
    scheduler.start()
    try:
        ids = scheduler.create(frozen.set_id, ["mock-reference", "mock-wrong"])
        await wait_until(lambda: len(store.run(ids[0])["results"]) >= 1)
        assert store.run(ids[1])["status"] == "queued"
        scheduler.control(ids[0], "cancel")
        count = len(store.run(ids[0])["results"])
        await scheduler.queue.join()
        assert store.run(ids[0])["status"] == "cancelled"
        assert len(store.run(ids[0])["results"]) == count
        assert store.run(ids[1])["status"] == "completed"
    finally:
        await scheduler.close()


def test_crash_recovery_does_not_change_completed_runs(store, frozen):
    id = store.create_run(frozen.set_id, store.get_model("mock-reference"))
    store.status(id, "running")
    p = frozen.problems[0]
    r = Result(
        index=0,
        problem_id=p.problem_id,
        status="correct",
        correct=True,
        answer="test",
        reason="test",
        latency_seconds=1,
    )
    store.save_result(id, r)
    store.save_result(id, r)
    store.recover()
    assert store.run(id)["status"] == "paused"
    assert len(store.run(id)["results"]) == 1
    store.status(id, "completed")
    store.recover()
    assert store.run(id)["status"] == "completed"


@pytest.mark.parametrize("startup_delay", [0, 1.2])
async def test_cancel_inflight_releases_next_run_immediately(store, monkeypatch, startup_delay):
    from llm_benchmark.adapters import MockAdapter
    from llm_benchmark.domain import SetConfig
    from llm_benchmark.sets import build_set

    # Cancellation needs one in-flight problem, not a 20-problem disk benchmark.
    frozen = build_set(SetConfig(generator_ids=["math.linear"], count=1, fixed_ratio=0))
    store.save_set(frozen)
    begin_attempt = store.begin_attempt
    first_attempt = True

    def prepare_attempt(id, index):
        nonlocal first_attempt
        if first_attempt:
            first_attempt = False
            # Model slow synchronous preparation/SQLite I/O on Windows runners.
            time.sleep(startup_delay)
        return begin_attempt(id, index)

    monkeypatch.setattr(store, "begin_attempt", prepare_attempt)

    entered, stopped = asyncio.Event(), asyncio.Event()
    next_entered, release_next = asyncio.Event(), asyncio.Event()

    class BlockingAdapter:
        async def complete(self, problem):
            entered.set()
            try:
                await asyncio.sleep(60)
            finally:
                stopped.set()

    class SuccessorAdapter(MockAdapter):
        async def complete(self, problem):
            next_entered.set()
            await release_next.wait()
            return await super().complete(problem)

    monkeypatch.setattr(
        "llm_benchmark.runner.make_adapter",
        lambda config: (
            BlockingAdapter() if config.model_id == "mock-reference" else SuccessorAdapter(config)
        ),
    )
    scheduler = Scheduler(store)
    scheduler.start()
    try:
        first, second = scheduler.create(frozen.set_id, ["mock-reference", "mock-wrong"])
        # Startup includes synchronous status/attempt commits. It is not the
        # cancellation latency assertion; slow CI disks can exceed one second.
        await asyncio.wait_for(entered.wait(), 30)
        scheduler.control(first, "cancel")
        await asyncio.wait_for(stopped.wait(), 1)
        # Keep cancellation at 1s and handoff at 3s, independently of startup.
        # The successor stays blocked until we prove the 60s request was cut short.
        await asyncio.wait_for(next_entered.wait(), 3)
        assert not store.run(first)["results"]
        assert store.run(first)["status"] == "cancelled"
        assert store.run(second)["status"] == "running"
        release_next.set()
        await asyncio.wait_for(scheduler.queue.join(), 30)
        assert store.run(second)["status"] == "completed"
        assert len(store.run(second)["results"]) == 1
    finally:
        await scheduler.close()


async def test_worker_metrics_survive_storage_and_report(store, frozen, monkeypatch):
    from llm_benchmark.domain import Response

    class MeasuredAdapter:
        async def complete(self, problem):
            return Response(text="fixture", metrics={"peak_ram_bytes": 123456, "load_seconds": 0.5})

    monkeypatch.setattr("llm_benchmark.runner.make_adapter", lambda config: MeasuredAdapter())
    scheduler = Scheduler(store)
    scheduler.start()
    try:
        id = scheduler.create(frozen.set_id, ["mock-reference"])[0]
        await scheduler.queue.join()
        result = summarize(store, id)["results"][0]
        assert result["metrics"]["peak_ram_bytes"] == 123456
        assert result["decode_tokens_per_second"] is None
    finally:
        await scheduler.close()


async def test_ollama_identity_observation_is_saved_before_answers_and_preserved_on_resume(
    store, frozen, monkeypatch
):
    import httpx

    from llm_benchmark.adapters import OllamaAdapter, mock_solve
    from llm_benchmark.domain import Response
    from llm_benchmark.reports import export_report

    digest = "a" * 64
    check_paths = []

    def handler(request):
        check_paths.append(request.url.path)
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "fixture:latest", "digest": digest}]}
            )
        return httpx.Response(200, json={"template": "fixture-template"})

    model = ModelConfig(model_id="observed", name="fixture", model="fixture", backend="ollama")
    store.save_model(model)
    scheduler = Scheduler(store)
    scheduler.start()
    id = None
    paused = False

    class FixtureAdapter(OllamaAdapter):
        async def complete(self, problem):
            nonlocal paused
            assert len(store.run(id)["environment"]["model_observations"]) >= 1
            if not paused:
                scheduler.control(id, "pause")
                paused = True
            return Response(text=mock_solve(problem.prompt))

    monkeypatch.setattr(
        "llm_benchmark.runner.make_adapter",
        lambda config: FixtureAdapter(config, httpx.MockTransport(handler)),
    )
    try:
        id = scheduler.create(frozen.set_id, [model.model_id])[0]
        await scheduler.queue.join()
        assert store.run_status(id) == "paused"
        first = summarize(store, id)
        assert first["completed"] == 1
        digest = "b" * 64
        scheduler.control(id, "resume")
        await scheduler.queue.join()
        report = summarize(store, id)
        observations = report["environment"]["model_observations"]
        assert [o["model_digest"] for o in observations] == ["a" * 64, "b" * 64]
        assert [o["completed_before"] for o in observations] == [0, 1]
        assert check_paths == ["/api/tags", "/api/show"] * 2
        assert report["correct"] == report["total"]
        assert report["results"][0]["metrics"]["model_observation_index"] == 0
        assert report["results"][1]["metrics"]["model_observation_index"] == 1
        assert report["model_identity_changed"]
        from llm_benchmark.analysis import calibration_rows

        with pytest.raises(ValueError, match="モデル識別情報"):
            calibration_rows(report)
        assert not comparison([first, report])["comparable"]
        assert "a" * 64 in export_report(report, "markdown")[0]
    finally:
        await scheduler.close()


async def test_cancel_during_model_observation_keeps_worker_alive(store, frozen, monkeypatch):
    from llm_benchmark.adapters import OllamaAdapter

    started = asyncio.Event()

    class WaitingAdapter(OllamaAdapter):
        async def check(self):
            started.set()
            await asyncio.Event().wait()

    store.save_model(ModelConfig(model_id="wait", name="fixture", backend="ollama"))
    original = __import__("llm_benchmark.runner", fromlist=["make_adapter"]).make_adapter
    monkeypatch.setattr(
        "llm_benchmark.runner.make_adapter",
        lambda config: WaitingAdapter(config) if config.backend == "ollama" else original(config),
    )
    scheduler = Scheduler(store)
    scheduler.start()
    try:
        id = scheduler.create(frozen.set_id, ["wait"])[0]
        await started.wait()
        scheduler.control(id, "cancel")
        await scheduler.queue.join()
        assert store.run_status(id) == "cancelled"
        assert store.run(id)["results"] == []
        assert "model_observations" not in store.run(id)["environment"]
        next_id = scheduler.create(frozen.set_id, ["mock-reference"])[0]
        await scheduler.queue.join()
        assert store.run_status(next_id) == "completed"
    finally:
        await scheduler.close()


def test_delete_requires_terminal_and_finished_worker(store, frozen):
    from llm_benchmark.runner import Scheduler

    scheduler = Scheduler(store)
    id = store.create_run(frozen.set_id, store.get_model("mock-reference"))
    for status in ["queued", "running", "pausing", "paused"]:
        store.status(id, status)
        with pytest.raises(ValueError, match="完了または中止"):
            scheduler.delete_run(id)
    store.status(id, "cancelled")
    scheduler.processing = id
    with pytest.raises(ValueError, match="終了を待って"):
        scheduler.delete_run(id)
    scheduler.processing = None
    scheduler.delete_run(id)
    with pytest.raises(KeyError):
        store.run(id)


@pytest.mark.asyncio
async def test_deleted_queue_entry_does_not_stop_worker(store, frozen):
    from llm_benchmark.runner import Scheduler

    scheduler = Scheduler(store)
    first, second = scheduler.create(frozen.set_id, ["mock-reference", "mock-wrong"])
    scheduler.control(first, "cancel")
    scheduler.delete_run(first)
    store.delete_model("mock-wrong")
    task = asyncio.create_task(scheduler.worker())
    try:
        await asyncio.wait_for(scheduler.queue.join(), timeout=5)
        assert store.run_status(second) == "completed"
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
