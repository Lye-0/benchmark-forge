import pytest

from llm_benchmark.analysis import calibration_rows, difficulty_estimate
from llm_benchmark.domain import Result
from llm_benchmark.runner import Scheduler, comparison, summarize
from llm_benchmark.speed_probe import SpeedConfig, build_speed_probe


def test_threshold_never_bridges_missing_low_difficulty():
    bins = [
        {"lower": i, "upper": i + 10, "completed": 20, "observed_wilson_95": [0.84, 1]}
        for i in range(0, 100, 10)
    ]
    assert difficulty_estimate(bins, eligible=True)["value"] == 100
    bins[3]["completed"] = 1
    assert difficulty_estimate(bins, eligible=True)["value"] == 30
    bins[0]["completed"] = 0
    assert difficulty_estimate(bins, eligible=True)["value"] is None
    assert difficulty_estimate(bins, eligible=False)["value"] is None


async def test_speed_workload_is_separate_and_reproducible(store):
    a, b = build_speed_probe(SpeedConfig()), build_speed_probe(SpeedConfig())
    assert a.set_hash == b.set_hash
    store.save_set(a)
    scheduler = Scheduler(store)
    scheduler.start()
    try:
        id = scheduler.create(a.set_id, ["mock-reference"])[0]
        await scheduler.queue.join()
        report = summarize(store, id)
        assert report["measurement_kind"] == "speed"
        assert report["correct"] == 3
        with pytest.raises(ValueError):
            calibration_rows(report)
        altered = {**report, "measurement_kind": "ability"}
        assert not comparison([report, altered])["comparable"]
    finally:
        await scheduler.close()


def test_calibration_observations_exclude_mock_and_preserve_lineage(store, frozen):
    id = store.create_run(frozen.set_id, store.get_model("mock-reference"))
    p = frozen.problems[0]
    store.save_result(
        id,
        Result(
            index=0,
            problem_id=p.problem_id,
            status="error",
            correct=False,
            answer="",
            reason="fixture",
            latency_seconds=1,
        ),
    )
    report = summarize(store, id)
    with pytest.raises(ValueError):
        calibration_rows(report)
    # Pure report contract test; no fake result is stored as an actual model measurement.
    report.update(test_only=False, provisional=False)
    rows = calibration_rows(report)
    assert rows[0]["empirical_difficulty"] is None
    assert rows[0]["set_hash"] == frozen.set_hash
    assert rows[0]["status"] == "error"
    assert rows[0]["attempt_count"] == 1


def test_output_diagnostics_preserve_scores_and_exclude_attempt_history(store, frozen):
    from llm_benchmark.reports import export_report

    run_id = store.create_run(frozen.set_id, store.get_model("mock-reference"))
    cases = [
        ("empty", {"done_reason": "length", "output_tokens": 4096}),
        ("correct", {"done_reason": "length"}),
        ("empty", {"output_tokens": 4096}),
        ("empty", {"done_reason": "stop"}),
        ("incorrect", {"done_reason": "unknown"}),
    ]
    for index, (status, metrics) in enumerate(cases):
        result = Result(
            index=index,
            problem_id=frozen.problems[index].problem_id,
            status=status,
            correct=status == "correct",
            answer="answer" if status != "empty" else "",
            reason="fixture",
            latency_seconds=1,
            metrics=metrics,
        )
        store.save_result(run_id, result)
        if index == 0:
            store.save_result(run_id, result)
    report = summarize(store, run_id)
    assert report["completed"] == 5
    assert report["correct"] == 1
    assert report["status_counts"]["empty"] == 3
    assert report["output_diagnostics"] == {
        "length_limited": 2,
        "empty_length_limited": 1,
        "empty_other_or_unknown": 2,
        "finish_reason_recorded": 3,
    }
    markdown, mime = export_report(report, "markdown")
    assert mime == "text/markdown"
    assert "出力上限による終了: 2件 / うち無回答: 1件" in markdown
    assert "| 無回答 | 3 |" in markdown
    assert '"max_tokens":' in markdown
    assert report["model"]["name"] in markdown
    assert "暫定" in markdown
    # Older exported reports can still be rendered without recorded diagnostics.
    del report["output_diagnostics"]
    assert "出力上限による終了: N/A" in export_report(report, "markdown")[0]
