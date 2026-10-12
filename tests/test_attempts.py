import sqlite3

from llm_benchmark.domain import Result
from llm_benchmark.storage import Store


def test_retry_preserves_history_and_current_unique_result(store, frozen):
    id = store.create_run(frozen.set_id, store.get_model("mock-reference"))
    p = frozen.problems[0]
    first = store.begin_attempt(id, 0)
    value = Result(
        index=0,
        problem_id=p.problem_id,
        status="timeout",
        correct=False,
        answer="",
        reason="timeout",
        latency_seconds=1,
    )
    store.save_result(id, value, first)
    store.save_result(id, value, first)
    store.retry_failed(id)
    assert not store.run(id)["results"]
    second = store.begin_attempt(id, 0)
    store.save_result(
        id, value.model_copy(update={"status": "correct", "correct": True, "answer": "ok"}), second
    )
    attempts = store.attempts(id)
    assert [a["ordinal"] for a in attempts] == [1, 2]
    assert [a["status"] for a in attempts] == ["timeout", "correct"]
    assert len(store.run(id)["results"]) == 1


def test_crash_interruption_and_v1_migration(store, frozen):
    id = store.create_run(frozen.set_id, store.get_model("mock-reference"))
    store.status(id, "running")
    store.begin_attempt(id, 0)
    store.recover()
    assert store.attempts(id)[0]["status"] == "interrupted"
    assert store.run_status(id) == "paused"
    value = Result(
        index=0,
        problem_id=frozen.problems[0].problem_id,
        status="correct",
        correct=True,
        answer="legacy",
        reason="ok",
        latency_seconds=1,
    )
    store.save_result(id, value)
    with sqlite3.connect(store.path) as con:
        con.execute("DROP TABLE attempts")
        con.execute("PRAGMA user_version=1")
    reopened = Store(store.path.parent)
    assert reopened.attempts(id)[0]["data"]["answer"] == "legacy"
    assert reopened.attempts(id)[0]["started_at"] is None
    assert len(Store(store.path.parent).attempts(id)) == 1


async def test_thousand_results_and_attempts_without_double_counting(store, monkeypatch):
    from llm_benchmark.domain import Response, SetConfig
    from llm_benchmark.runner import Scheduler, summarize
    from llm_benchmark.sets import build_set

    frozen = build_set(SetConfig(generator_ids=["math.expression"], count=1000, fixed_ratio=0))
    store.save_set(frozen)

    class FastFixture:
        async def complete(self, public):
            return Response(text="wrong fixture")

    monkeypatch.setattr("llm_benchmark.runner.make_adapter", lambda config: FastFixture())
    scheduler = Scheduler(store)
    scheduler.start()
    try:
        id = scheduler.create(frozen.set_id, ["mock-reference"])[0]
        await scheduler.queue.join()
        report = summarize(store, id)
        assert report["completed"] == 1000
        assert len(report["attempts"]) == 1000
        assert len({r["index"] for r in report["results"]}) == 1000
    finally:
        await scheduler.close()


def test_real_process_crash_preserves_committed_results(store, frozen):
    import subprocess
    import sys

    code = """import asyncio,os,sys
from pathlib import Path
from llm_benchmark.storage import Store
from llm_benchmark.runner import Scheduler
async def main():
 store=Store(Path(sys.argv[1]));scheduler=Scheduler(store);scheduler.start()
 id=scheduler.create(sys.argv[2],['mock-reference'])[0]
 while len(store.run(id)['results'])<2: await asyncio.sleep(.005)
 os._exit(17)
asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(store.path.parent), frozen.set_id], timeout=10
    )
    assert result.returncode == 17
    before = store.runs()[0]
    assert before["status"] == "running"
    store.recover()
    after = store.run(before["id"])
    assert after["status"] == "paused"
    assert len(after["results"]) == len(before["results"])
    assert any(a["status"] == "interrupted" for a in store.attempts(before["id"]))
