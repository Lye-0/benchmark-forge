import asyncio
import fcntl
import time
from collections import Counter
from contextlib import suppress
from typing import Literal, TextIO

from llm_benchmark.adapters import AdapterError, capabilities, make_adapter
from llm_benchmark.domain import ModelConfig, Result
from llm_benchmark.grading import grade
from llm_benchmark.storage import Store


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * p
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def summarize(store: Store, id: str, detail: bool = True) -> dict:
    run = store.run(id)
    frozen = store.get_set(run["set_id"])
    results: list[Result] = run["results"]
    by_id = {r.problem_id: r for r in results}
    total = len(frozen.problems)
    correct = sum(r.correct for r in results)
    status = Counter(r.status for r in results)
    weighted = sum(frozen.weights[r.problem_id] for r in results if r.correct)
    by_origin = {}
    by_category = {}
    by_difficulty = []
    by_format = {}
    by_tag = {}

    def group_summary(problems):
        selected = [by_id[p.problem_id] for p in problems if p.problem_id in by_id]
        n = len(problems)
        wins = sum(r.correct for r in selected)
        contribution = sum(frozen.weights[r.problem_id] for r in selected if r.correct)
        return {
            "total": n,
            "completed": len(selected),
            "correct": wins,
            "accuracy": wins / n if n else None,
            "weighted_contribution": contribution,
        }

    for origin in ["fixed", "dynamic"]:
        by_origin[origin] = group_summary([p for p in frozen.problems if p.origin == origin])
    for cat in sorted({p.category_id for p in frozen.problems}):
        by_category[cat] = group_summary([p for p in frozen.problems if p.category_id == cat])
    for type in sorted({p.grading_type for p in frozen.problems}):
        by_format[type] = group_summary([p for p in frozen.problems if p.grading_type == type])
    for tag in sorted({tag for p in frozen.problems for tag in p.tags}):
        by_tag[tag] = group_summary([p for p in frozen.problems if tag in p.tags])
    for lower in range(0, 100, 10):
        subset = [
            p
            for p in frozen.problems
            if lower <= p.target_difficulty
            and (p.target_difficulty < lower + 10 or (lower == 90 and p.target_difficulty == 100))
        ]
        group = group_summary(subset)
        # Wilson interval for observed completions only; bins are descriptive, not cross-field calibration.
        n = group["completed"]
        wins = group["correct"]
        interval = None
        if n:
            z = 1.96
            center = (wins / n + z * z / (2 * n)) / (1 + z * z / n)
            half = (
                z * ((wins / n * (1 - wins / n) / n + z * z / (4 * n * n)) ** 0.5) / (1 + z * z / n)
            )
            interval = [max(0, center - half), min(1, center + half)]
        by_difficulty.append(
            {"lower": lower, "upper": lower + 10, **group, "observed_wilson_95": interval}
        )
    latencies = [r.latency_seconds for r in results]
    report = {
        **{k: v for k, v in run.items() if k != "results"},
        "set_hash": frozen.set_hash,
        "profile_version": frozen.profile_version,
        "grader_version": frozen.grader_version,
        "total": total,
        "completed": len(results),
        "correct": correct,
        "accuracy": weighted,
        "micro_accuracy": correct / total,
        "completion_rate": sum(r.status in {"correct", "incorrect"} for r in results) / total,
        "status_counts": dict(status),
        "by_origin": by_origin,
        "by_category": by_category,
        "by_difficulty": by_difficulty,
        "by_format": by_format,
        "by_tag": by_tag,
        "latency_p50": percentile(latencies, 0.5),
        "latency_p95": percentile(latencies, 0.95),
        "answer_time_seconds": sum(latencies),
        "provisional": run["status"] != "completed",
        "test_only": run["model"]["backend"] == "mock",
        "warnings": frozen.warnings,
        "capabilities": capabilities(ModelConfig.model_validate(run["model"])),
    }
    if detail:
        report["results"] = [
            {**r.model_dump(), "problem": frozen.problems[r.index].model_dump()} for r in results
        ]
        report["config"] = frozen.config.model_dump()
        report["weights"] = frozen.weights
    return report


def comparison(reports: list[dict]) -> dict:
    warnings = []
    comparable = (
        len({r["set_hash"] for r in reports}) <= 1
        and len({r["grader_version"] for r in reports}) <= 1
    )
    if not comparable:
        warnings.append("問題セットまたは採点器が異なるため、能力スコアを直接比較できません。")
    if any(r["test_only"] for r in reports):
        warnings.append("Mock結果はソフトウェア診断です。正式なモデルランキングには含めません。")
    if any(r["provisional"] for r in reports):
        warnings.append("未完了ランを含みます。正答率は暫定値です。")
    if len({str(r["environment"]) for r in reports}) > 1:
        warnings.append("実行環境が異なります。速度・メモリを直接比較できません。")
    if (
        len(
            {
                (r["model"]["temperature"], r["model"]["max_tokens"], r["model"]["timeout_seconds"])
                for r in reports
            }
        )
        > 1
    ):
        warnings.append("推論パラメーターが異なります。")
    return {"comparable": comparable, "warnings": warnings, "runs": reports}


class Scheduler:
    def __init__(self, store: Store):
        self.store = store
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.task: asyncio.Task | None = None
        self.lock: TextIO | None = None

    def start(self):
        self.lock = (self.store.path.parent / "runner.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.lock.close()
            self.lock = None
            raise RuntimeError(
                "同じデータ領域で別の評価プロセスが動いています。APIとCLIを同時に実行しないでください"
            ) from exc
        self.store.recover()
        self.task = asyncio.create_task(self.worker())

    async def close(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        self.store.recover()
        if self.lock:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()
            self.lock = None

    def create(self, set_id: str, models: list[str]) -> list[str]:
        self.store.get_set(set_id)
        if len(models) != len(set(models)):
            raise ValueError("モデルの重複選択はできません")
        configs = [self.store.get_model(id) for id in models]
        for config in configs:
            make_adapter(config)  # Preflight all before creating any jobs.
        ids = [self.store.create_run(set_id, config) for config in configs]
        for id in ids:
            self.queue.put_nowait(id)
        return ids

    def control(self, id: str, action: str):
        run = self.store.run(id)
        status = run["status"]
        if action == "pause" and status in {"running", "queued"}:
            self.store.status(id, "pausing" if status == "running" else "paused")
        elif action == "cancel" and status in {"queued", "running", "pausing", "paused"}:
            self.store.status(id, "cancelled")
        elif action == "resume" and status == "paused":
            self.store.status(id, "queued")
            self.queue.put_nowait(id)
        elif action == "retry" and status in {"completed", "paused"}:
            self.store.retry_failed(id)
            self.store.status(id, "queued")
            self.queue.put_nowait(id)
        else:
            raise ValueError(f"{status} のランには {action} を実行できません")

    async def worker(self):
        while True:
            id = await self.queue.get()
            try:
                await self.execute(id)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.store.status(id, "paused")
            finally:
                self.queue.task_done()

    async def execute(self, id: str):
        run = self.store.run(id)
        if run["status"] != "queued":
            return
        self.store.status(id, "running")
        frozen = self.store.get_set(run["set_id"])
        config = ModelConfig.model_validate(run["model"])
        adapter = make_adapter(config)
        done = {r.index for r in run["results"]}
        for index, problem in enumerate(frozen.problems):
            status = self.store.run(id)["status"]
            if status == "pausing":
                self.store.status(id, "paused")
                return
            if status != "running":
                return
            if index in done:
                continue
            start = time.perf_counter()
            answer, reason, correct = "", "", False
            outcome: Literal["correct", "incorrect", "timeout", "error", "empty", "ungradable"] = (
                "error"
            )
            tokens = speed = ttft = None
            try:
                response = await asyncio.wait_for(
                    adapter.complete(problem.public()), timeout=config.timeout_seconds
                )
                answer = response.text
                tokens = response.output_tokens
                ttft = response.ttft_seconds
                if tokens is not None and response.decode_seconds and response.decode_seconds > 0:
                    speed = tokens / response.decode_seconds
                if not answer.strip() and problem.answer_spec.expected != "":
                    outcome, reason = "empty", "無回答"
                else:
                    result = grade(answer, problem.answer_spec)
                    correct, reason = result.correct, result.reason
                    outcome = "correct" if correct else "incorrect"
            except TimeoutError:
                outcome, reason = "timeout", "応答タイムアウト"
            except AdapterError as e:
                reason = str(e)
            except Exception:
                reason = "モデル応答処理に失敗しました（詳細は秘密情報保護のため非表示）"
            # A cancellation during an in-flight request must not write a late answer.
            if self.store.run(id)["status"] == "cancelled":
                return
            self.store.save_result(
                id,
                Result(
                    index=index,
                    problem_id=problem.problem_id,
                    status=outcome,
                    correct=correct,
                    answer=answer,
                    reason=reason,  # type: ignore[arg-type]
                    latency_seconds=time.perf_counter() - start,
                    output_tokens=tokens,
                    decode_tokens_per_second=speed,
                    ttft_seconds=ttft,
                ),
            )
        status = self.store.run(id)["status"]
        if status in {"running", "pausing"}:
            self.store.status(id, "completed")
