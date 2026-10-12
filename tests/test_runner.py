import asyncio

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


async def test_cancel_inflight_releases_next_run_immediately(store, frozen, monkeypatch):
    from llm_benchmark.adapters import MockAdapter

    entered, stopped = asyncio.Event(), asyncio.Event()

    class BlockingAdapter:
        async def complete(self, problem):
            entered.set()
            try:
                await asyncio.sleep(60)
            finally:
                stopped.set()

    monkeypatch.setattr(
        "llm_benchmark.runner.make_adapter",
        lambda config: (
            BlockingAdapter() if config.model_id == "mock-reference" else MockAdapter(config)
        ),
    )
    scheduler = Scheduler(store)
    scheduler.start()
    try:
        first, second = scheduler.create(frozen.set_id, ["mock-reference", "mock-wrong"])
        await asyncio.wait_for(entered.wait(), 1)
        scheduler.control(first, "cancel")
        await asyncio.wait_for(stopped.wait(), 1)
        await asyncio.wait_for(scheduler.queue.join(), 3)
        assert not store.run(first)["results"]
        assert store.run(first)["status"] == "cancelled"
        assert store.run(second)["status"] == "completed"
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
