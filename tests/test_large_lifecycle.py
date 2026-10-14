"""Small CI failure regression; the opt-in profiler exercises 8,000 problems."""

import sqlite3

import pytest

from llm_benchmark.archive import split_archive, verify_archive
from llm_benchmark.domain import Result, SetConfig
from llm_benchmark.runner import summarize
from llm_benchmark.sets import build_set
from llm_benchmark.storage import Store


def test_transaction_failure_recovery_retry_pages_and_archive(store, tmp_path):
    count = 60  # Cross the production 50-row page boundary without a slow CI load test.
    frozen = build_set(SetConfig(generator_ids=["math.expression"], count=count, fixed_ratio=0))
    store.save_set(frozen)
    run_id = store.create_run(frozen.set_id, store.get_model("mock-reference"))
    store.status(run_id, "running")

    def value(index, *, timeout=False):
        correct = index % 2 == 0 and not timeout
        return Result(
            index=index,
            problem_id=frozen.problems[index].problem_id,
            status="timeout" if timeout else "correct" if correct else "incorrect",
            correct=correct,
            answer="fixture",
            reason="fixture",
            latency_seconds=0.001,
        )

    for index in range(10):
        attempt = store.begin_attempt(run_id, index)
        store.save_result(run_id, value(index, timeout=index == 0), attempt)
        store.save_result(run_id, value(index, timeout=index == 0), attempt)
    interrupted = store.begin_attempt(run_id, 10)
    # Fail after the result INSERT but before its attempt UPDATE can commit.
    with store.connection() as con:
        con.execute("""CREATE TRIGGER fail_attempt BEFORE UPDATE ON attempts
            WHEN NEW.idx = 10 AND NEW.status = 'correct'
            BEGIN SELECT RAISE(ABORT, 'fixture disk failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="fixture disk failure"):
        store.save_result(run_id, value(10), interrupted)
    with store.connection() as con:
        assert (
            con.execute("SELECT count(*) FROM results WHERE run_id=?", (run_id,)).fetchone()[0]
            == 10
        )
        con.execute("DROP TRIGGER fail_attempt")
    store.status(run_id, "pausing")
    restored = Store(store.path.parent)
    restored.recover()
    restored.recover()
    assert restored.run_status(run_id) == "paused"
    assert restored.attempts(run_id)[-1]["status"] == "interrupted"
    partial = summarize(restored, run_id, detail=False)
    assert partial["completed"] == 10 and partial["correct"] == 4
    assert partial["total"] == count and partial["micro_accuracy"] == 4 / count
    # A late completion for the interrupted attempt rolls back its provisional INSERT.
    with pytest.raises(ValueError, match="試行と結果"):
        restored.save_result(run_id, value(10), interrupted)
    assert summarize(restored, run_id, detail=False)["completed"] == 10
    restored.retry_failed(run_id)
    assert summarize(restored, run_id, detail=False)["completed"] == 9
    restored.status(run_id, "running")
    for index in [0, *range(10, count)]:
        attempt = restored.begin_attempt(run_id, index)
        restored.save_result(run_id, value(index), attempt)
        restored.save_result(run_id, value(index), attempt)
    restored.status(run_id, "completed")
    compact = summarize(restored, run_id, detail=False)
    assert "results" not in compact and "attempts" not in compact
    assert compact["completed"] == compact["total"] == count
    assert compact["correct"] == 30
    assert compact["accuracy"] == pytest.approx(0.5)
    assert compact["micro_accuracy"] == 0.5
    pages = [restored.result_page(run_id, offset=offset, limit=50) for offset in (0, 50)]
    assert [len(page["results"]) for page in pages] == [50, 10]
    assert [row["index"] for page in pages for row in page["results"]] == list(range(count))
    attempts = [row for page in pages for row in page["attempts"]]
    assert len(attempts) == count + 2
    assert [row["status"] for row in attempts if row["idx"] == 0] == ["timeout", "correct"]
    assert [row["status"] for row in attempts if row["idx"] == 10] == ["interrupted", "correct"]
    destination = tmp_path / "archive"
    manifest = split_archive(restored, run_id, destination, 8000, True)
    assert manifest["records"] == 1 + count * 3 + 2
    assert manifest["set_hash"] == frozen.set_hash
    assert verify_archive(destination)["verified"]
    assert Store(store.path.parent).get_set(frozen.set_id).set_hash == frozen.set_hash
