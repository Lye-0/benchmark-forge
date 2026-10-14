"""Opt-in storage lifecycle load check, using deterministic fixtures and no LLM.

uv run python scripts/profile_lifecycle.py --count 8000
Uses a new temporary directory unless --output is supplied (must not exist).
RSS peaks are process cumulative; timings describe this fixture, not days of use.
"""

import argparse
import json
import math
import platform
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import psutil

from llm_benchmark.archive import split_archive, verify_archive
from llm_benchmark.domain import Result, SetConfig
from llm_benchmark.runner import summarize
from llm_benchmark.sets import build_set
from llm_benchmark.storage import Store


def memory() -> dict:
    info = psutil.Process().memory_info()
    if sys.platform == "win32":
        peak = psutil.Process().memory_info().peak_wset
    else:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if platform.system() != "Darwin":
            peak *= 1024
    return {"rss_bytes": info.rss, "process_peak_rss_bytes": peak}


@contextmanager
def measure(stage: str, metrics: dict):
    start = time.perf_counter()
    yield
    metrics[stage] = {"seconds": round(time.perf_counter() - start, 6), **memory()}
    print(json.dumps({"stage": stage, **metrics[stage]}), flush=True)


def profile(directory: Path, count: int) -> dict:
    metrics: dict = {}
    store = Store(directory / "data")
    with measure("generation", metrics):
        frozen = build_set(SetConfig(generator_ids=["math.expression"], count=count, fixed_ratio=0))
    with measure("save_set", metrics):
        store.save_set(frozen)
    run_id = store.create_run(frozen.set_id, store.get_model("mock-reference"))
    store.status(run_id, "running")

    def save(index: int, *, timeout: bool = False):
        correct = index % 2 == 0 and not timeout
        value = Result(
            index=index,
            problem_id=frozen.problems[index].problem_id,
            status="timeout" if timeout else "correct" if correct else "incorrect",
            correct=correct,
            answer="synthetic fixture",
            reason="storage load fixture",
            latency_seconds=0.001,
        )
        attempt = store.begin_attempt(run_id, index)
        store.save_result(run_id, value, attempt)
        # Simulated duplicate delivery must not add a result or attempt.
        store.save_result(run_id, value, attempt)

    midpoint = count // 2
    with measure("first_half_writes", metrics):
        for index in range(midpoint):
            save(index, timeout=index == 0)
    store.begin_attempt(run_id, midpoint)
    store.status(run_id, "pausing")
    with measure("reopen_recover", metrics):
        store = Store(directory / "data")
        store.recover()
        store.recover()  # Recovery is safe to replay.
        assert store.run_status(run_id) == "paused"
        partial = summarize(store, run_id, detail=False)
        assert partial["completed"] == midpoint and partial["total"] == count
        assert partial["micro_accuracy"] == ((midpoint + 1) // 2 - 1) / count
        store.retry_failed(run_id)
        assert summarize(store, run_id, detail=False)["completed"] == midpoint - 1
    with measure("resume_writes", metrics):
        store.status(run_id, "running")
        save(0)
        for index in range(midpoint, count):
            save(index)
        store.status(run_id, "completed")
    with measure("summary_detail_false", metrics):
        report = summarize(store, run_id, detail=False)
        assert "results" not in report and "attempts" not in report
        assert report["completed"] == report["total"] == count
        assert report["correct"] == (count + 1) // 2
        assert math.isclose(report["accuracy"], report["correct"] / count)
        assert report["micro_accuracy"] == report["correct"] / count
    with measure("all_log_pages_50", metrics):
        observed = 0
        attempt_count = 0
        for offset in range(0, count, 50):
            page = store.result_page(run_id, offset=offset, limit=50)
            assert page["total"] == count
            assert [r["index"] for r in page["results"]] == list(
                range(offset, min(offset + 50, count))
            )
            observed += len(page["results"])
            attempt_count += len(page["attempts"])
        assert observed == count and attempt_count == count + 2
    with measure("split_archive", metrics):
        manifest = split_archive(store, run_id, directory / "archive", 1024 * 1024, True)
        assert manifest["records"] == 1 + count * 3 + 2
        assert manifest["set_hash"] == frozen.set_hash
    with measure("verify_archive", metrics):
        assert verify_archive(directory / "archive")["verified"]
    result = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "fixture": "math.expression dynamic; synthetic alternating correct/incorrect; no model",
        "count": count,
        "set_hash": frozen.set_hash,
        "seed": 42,
        "completed": report["completed"],
        "correct": report["correct"],
        "denominator": report["total"],
        "accuracy": report["accuracy"],
        "attempts": attempt_count,
        "archive_records": manifest["records"],
        "archive_parts": len(manifest["parts"]),
        "metrics": metrics,
        "limits": "Single-process storage fixture, not scheduler or multi-day endurance; all problems retained during profiling.",
    }
    (directory / "profile.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=8000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 2 <= args.count <= 8000:
        parser.error("count must be between 2 and 8000")
    if args.output:
        args.output.mkdir(parents=True, exist_ok=False)
        print(json.dumps(profile(args.output, args.count)), flush=True)
    else:
        with tempfile.TemporaryDirectory(prefix="forge-lifecycle-") as root:
            print(json.dumps(profile(Path(root), args.count)), flush=True)


if __name__ == "__main__":
    main()
