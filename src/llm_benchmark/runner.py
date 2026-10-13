import asyncio
import time
from collections import Counter
from contextlib import suppress
from typing import BinaryIO, Literal

from llm_benchmark.adapters import AdapterError, OllamaAdapter, capabilities, make_adapter
from llm_benchmark.analysis import (
    difficulty_estimate,
    output_summary,
    resource_summary,
    timing_summary,
)
from llm_benchmark.domain import ModelConfig, Result
from llm_benchmark.gpu_sampling import GpuSampler
from llm_benchmark.grading import grade
from llm_benchmark.platform_support import acquire_lock, release_lock
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
    run = store.run(id, include_payloads=detail)
    frozen = store.get_set(run["set_id"], metadata_only=not detail)
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
        **{k: v for k, v in run.items() if k not in {"results", "_recent_results"}},
        "set_hash": frozen.set_hash,
        "set_metadata": frozen.metadata,
        "config": frozen.config.model_dump(),
        "profile_version": frozen.profile_version,
        "grader_version": frozen.grader_version,
        "total": total,
        "completed": len(results),
        "correct": correct,
        "accuracy": weighted,
        "micro_accuracy": correct / total,
        "completion_rate": sum(r.status in {"correct", "incorrect"} for r in results) / total,
        "status_counts": dict(status),
        "output_diagnostics": output_summary(results),
        "by_origin": by_origin,
        "by_category": by_category,
        "by_difficulty": by_difficulty,
        "by_format": by_format,
        "by_tag": by_tag,
        "difficulty_80": difficulty_estimate(
            by_difficulty,
            eligible=run["status"] == "completed"
            and run["model"]["backend"] != "mock"
            and frozen.profile_version != "Speed probe v1"
            and frozen.config.evaluation_mode == "text",
        ),
        "resources": resource_summary(results),
        "measurement_kind": "speed"
        if frozen.profile_version == "Speed probe v1"
        else frozen.config.evaluation_mode,
        "latency_p50": percentile(latencies, 0.5),
        "latency_p95": percentile(latencies, 0.95),
        "answer_time_seconds": sum(latencies),
        "timing": timing_summary(results, run["_recent_results"], total, run["status"]),
        "provisional": run["status"] != "completed",
        "test_only": run["model"]["backend"] == "mock",
        "warnings": frozen.warnings,
        "capabilities": capabilities(ModelConfig.model_validate(run["model"])),
    }
    observations = run["environment"].get("model_observations", [])
    report["model_identity_changed"] = any(
        len({item[key] for item in observations if item.get(key)}) > 1
        for key in ("model_digest", "template_hash")
    )
    if report["model_identity_changed"]:
        report["warnings"] = [
            *report["warnings"],
            "実行区間の間でモデルまたはテンプレートの識別情報が変わっています。結果が混在するため直接比較できません。",
        ]
    if run["model"].get("backend") == "ollama":
        if not observations or any(not item.get("model_digest") for item in observations):
            report["warnings"] = [
                *report["warnings"],
                "モデルdigestが未取得の区間があります。同じモデル名でも同じ内容だったかは確認できません。",
            ]
    if detail:
        report["attempts"] = store.attempts(id)
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
        and len({r.get("measurement_kind", "ability") for r in reports}) <= 1
    )
    if not comparable:
        warnings.append("問題セットまたは採点器が異なるため、能力スコアを直接比較できません。")
    if any(r.get("model_identity_changed", False) for r in reports):
        comparable = False
        warnings.append("実行途中でモデル識別情報が変わったランを含むため直接比較できません。")
    if any(r["test_only"] for r in reports):
        warnings.append("Mock結果はソフトウェア診断です。正式なモデルランキングには含めません。")
    if any(r["provisional"] for r in reports):
        warnings.append("未完了ランを含みます。正答率は暫定値です。")
    if (
        len(
            {
                str({k: v for k, v in r["environment"].items() if k != "model_observations"})
                for r in reports
            }
        )
        > 1
    ):
        warnings.append("実行環境が異なります。速度・メモリを直接比較できません。")
    if (
        len(
            {
                (
                    r["model"]["temperature"],
                    r["model"]["max_tokens"],
                    r["model"]["timeout_seconds"],
                    r["model"].get("context_length"),
                    r["model"].get("device"),
                    r["model"].get("streaming", False),
                    r["model"].get("gpu_sampling", False),
                    r["model"].get("inference_seed", 0),
                )
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
        self.lock: BinaryIO | None = None
        self.active: tuple[str, asyncio.Task] | None = None
        from llm_benchmark.sandbox import DockerSandbox

        self.sandbox = DockerSandbox()

    def start(self):
        if self.lock is not None:
            raise RuntimeError("評価プロセスは既に起動しています")
        try:
            self.lock = acquire_lock(self.store.path.parent / "runner.lock")
        except OSError as exc:
            raise RuntimeError(
                "データ領域をロックできません。別の評価プロセス（API/CLI）実行または保存先の権限を確認してください"
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
            release_lock(self.lock)
            self.lock = None

    def create(self, set_id: str, models: list[str]) -> list[str]:
        frozen = self.store.get_set(set_id, metadata_only=True)
        if len(models) != len(set(models)):
            raise ValueError("モデルの重複選択はできません")
        if frozen.config.evaluation_mode == "code" and not self.sandbox.verified:
            raise AdapterError("コード評価の前に隔離検証を実行してください")
        configs = [self.store.get_model(id) for id in models]
        for config in configs:
            if (
                frozen.config.evaluation_mode in {"native-tools", "agent"}
                and not capabilities(config)["native_tools"]
            ):
                raise AdapterError(
                    "選択したモデルはネイティブツールに未対応です。通常の誤答には計上しません"
                )
            make_adapter(config)  # Preflight all before creating any jobs.
        ids = [self.store.create_run(set_id, config) for config in configs]
        for id in ids:
            self.queue.put_nowait(id)
        return ids

    def control(self, id: str, action: str):
        status = self.store.run_status(id)
        if action == "pause" and status in {"running", "queued"}:
            self.store.status(id, "pausing" if status == "running" else "paused")
        elif action == "cancel" and status in {"queued", "running", "pausing", "paused"}:
            self.store.status(id, "cancelled")
            if self.active and self.active[0] == id:
                self.active[1].cancel()
        elif action == "resume" and status == "paused":
            self.store.status(id, "queued")
            self.queue.put_nowait(id)
        elif action == "retry" and status in {"completed", "paused"}:
            self.store.retry_failed(id)
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
        run = self.store.run(id, include_payloads=False)
        if run["status"] != "queued":
            return
        self.store.status(id, "running")
        frozen = self.store.set_header(run["set_id"])
        config = ModelConfig.model_validate(run["model"])
        adapter = make_adapter(config)
        observation_index = None
        if isinstance(adapter, OllamaAdapter):
            observation_started = time.perf_counter()
            check = asyncio.create_task(adapter.check())
            self.active = (id, check)
            try:
                observation = await asyncio.wait_for(check, timeout=8)
            except TimeoutError:
                observation = {
                    "status": "unavailable",
                    "reason": "モデル識別情報の取得がタイムアウトしました",
                }
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current and current.cancelling():
                    raise
                return
            finally:
                self.active = None
            observation_index = self.store.record_model_observation(
                id,
                {
                    key: observation.get(key)
                    for key in (
                        "status",
                        "reason",
                        "model_digest",
                        "digest_scope",
                        "template_hash",
                        "context_length",
                    )
                }
                | {
                    "metadata_seconds": time.perf_counter() - observation_started,
                    "completed_before": len(run["results"]),
                },
            )
        done = {r.index for r in run["results"]}
        for index, problem in enumerate(self.store.iter_problems(run["set_id"])):
            status = self.store.run_status(id)
            if status == "pausing":
                self.store.status(id, "paused")
                return
            if status != "running":
                return
            if index in done:
                continue
            attempt = self.store.begin_attempt(id, index)
            start = time.perf_counter()
            answer, reason, correct = "", "", False
            outcome: Literal["correct", "incorrect", "timeout", "error", "empty", "ungradable"] = (
                "error"
            )
            tokens = speed = ttft = None
            metrics = {}
            sampler = GpuSampler(config.gpu_sampling)
            sampler.start()
            try:
                from llm_benchmark.tool_eval import evaluate_tools

                operation = (
                    evaluate_tools(config, problem, frozen["config"]["evaluation_mode"])
                    if frozen["config"]["evaluation_mode"] in {"native-tools", "agent"}
                    else adapter.complete(problem.public())
                )
                pending = asyncio.create_task(operation)
                self.active = (id, pending)
                try:
                    response = await asyncio.wait_for(pending, timeout=config.timeout_seconds)
                finally:
                    self.active = None
                metrics = response.metrics
                answer = response.text
                tokens = response.output_tokens
                ttft = response.ttft_seconds
                if tokens is not None and response.decode_seconds and response.decode_seconds > 0:
                    speed = tokens / response.decode_seconds
                if frozen["config"]["evaluation_mode"] == "code":
                    from llm_benchmark.code_eval import harness

                    code_task = asyncio.create_task(
                        self.sandbox.execute(harness(answer, problem.simulation["cases"]))
                    )
                    self.active = (id, code_task)
                    try:
                        code_result = await code_task
                    finally:
                        self.active = None
                    metrics.update(
                        sandbox_status=code_result.status, sandbox_exit_code=code_result.exit_code
                    )
                    if code_result.status == "ok":
                        graded = grade(code_result.stdout.strip(), problem.answer_spec)
                        correct, reason = graded.correct, graded.reason
                        outcome = "correct" if correct else "incorrect"
                    else:
                        outcome = "timeout" if code_result.status == "timeout" else "error"
                        reason = "隔離コード実行: " + code_result.status
                elif not answer.strip() and problem.answer_spec.expected != "":
                    outcome, reason = "empty", "無回答"
                else:
                    result = grade(answer, problem.answer_spec)
                    correct, reason = result.correct, result.reason
                    outcome = "correct" if correct else "incorrect"
            except asyncio.CancelledError:
                # A user cancellation stops this request, not the scheduler or the next run.
                self.store.end_attempt(
                    attempt,
                    "cancelled" if self.store.run_status(id) == "cancelled" else "interrupted",
                )
                current = asyncio.current_task()
                if (
                    self.store.run_status(id) == "cancelled"
                    and current
                    and not current.cancelling()
                ):
                    return
                raise
            except TimeoutError:
                outcome, reason = "timeout", "応答タイムアウト"
            except AdapterError as e:
                reason = str(e)
            except Exception:
                reason = "モデル応答処理に失敗しました（詳細は秘密情報保護のため非表示）"
            finally:
                answer_elapsed = time.perf_counter() - start
                await sampler.close()
            if config.gpu_sampling:
                metrics["gpu_sampling"] = sampler.summary()
            # A cancellation during an in-flight request must not write a late answer.
            if self.store.run_status(id) == "cancelled":
                self.store.end_attempt(attempt, "cancelled")
                return
            if observation_index is not None:
                metrics["model_observation_index"] = observation_index
            self.store.save_result(
                id,
                Result(
                    index=index,
                    problem_id=problem.problem_id,
                    status=outcome,
                    correct=correct,
                    answer=answer,
                    reason=reason,  # type: ignore[arg-type]
                    latency_seconds=answer_elapsed,
                    output_tokens=tokens,
                    decode_tokens_per_second=speed,
                    ttft_seconds=ttft,
                    metrics=metrics,
                ),
                attempt=attempt,
            )
        status = self.store.run_status(id)
        if status in {"running", "pausing"}:
            self.store.status(id, "completed")
