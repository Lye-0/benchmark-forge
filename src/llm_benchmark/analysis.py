"""Descriptive estimates only: never silently calibrate cross-domain difficulty."""


def difficulty_estimate(bins: list[dict], *, eligible: bool) -> dict:
    base = {
        "value": None,
        "target_accuracy": 0.8,
        "minimum_per_bin": 20,
        "method": "consecutive bins from zero whose pointwise Wilson 95% lower bound is at least 0.8",
        "calibrated": False,
    }
    if not eligible:
        return {**base, "reason": "完了した実モデルのランのみ対象（Mock・専用速度試験を除外）"}
    reached = None
    for bin in bins:
        if bin["completed"] < 20:
            return {
                **base,
                "value": reached,
                "reason": f"難易度{bin['lower']}〜{bin['upper']}の回答数不足。以降を推定しません",
            }
        interval = bin["observed_wilson_95"]
        if not interval or interval[0] < 0.8:
            return {
                **base,
                "value": reached,
                "reason": "80%達成を支持する区間が途切れました。未校正の記述的指標です",
            }
        reached = bin["upper"]
    return {
        **base,
        "value": reached,
        "reason": "全区間で条件を満たしました。点ごとの区間であり同時信頼保証ではありません",
    }


def resource_summary(results: list) -> dict:
    keys = ["peak_ram_bytes", "peak_vram_allocated_bytes", "load_seconds", "generation_seconds"]
    output = {}
    for key in keys:
        values = [r.metrics[key] for r in results if isinstance(r.metrics.get(key), (int, float))]
        output[key] = max(values) if values else None
        output[key + "_samples"] = len(values)
    from llm_benchmark.gpu_sampling import summarize_gpu

    output["gpu_sampling"] = summarize_gpu(results)
    output["scope"] = (
        "ワーカー指標は成功応答に含まれた局所計測の最大値。gpu_samplingは別集計で、ホストGPU全体を対象にエラー・タイムアウト時の取得値も含みます"
    )
    return output


def calibration_rows(report: dict) -> list[dict]:
    """Export observations, not fitted or asserted empirical difficulty values."""
    if report.get("model_identity_changed", False):
        raise ValueError("モデル識別情報が変わったランは校正用データに使用できません")
    if (
        report["test_only"]
        or report["provisional"]
        or report["profile_version"] == "Speed probe v1"
        or report.get("measurement_kind", "text") != "text"
    ):
        raise ValueError("校正用データには完了した実モデルの能力評価ランが必要です")
    from collections import Counter

    attempts = Counter(a["idx"] for a in report["attempts"])
    return [
        {
            "run_id": report["id"],
            "set_hash": report["set_hash"],
            "model": report["model"],
            "grader_version": report["grader_version"],
            "problem_id": row["problem_id"],
            "generator_id": row["problem"]["generator_id"],
            "generator_version": row["problem"]["generator_version"],
            "category_id": row["problem"]["category_id"],
            "target_difficulty": row["problem"]["target_difficulty"],
            "empirical_difficulty": None,
            "correct": row["correct"],
            "status": row["status"],
            "attempt_count": attempts[row["index"]],
            "response_text_policy": row.get("metrics", {}).get("response_text_policy"),
            "visibility": report["set_metadata"].get("visibility", "public"),
        }
        for row in report["results"]
    ]


def output_summary(results: list) -> dict:
    """Observed backend termination only; never infer hidden reasoning or change scores."""
    limited = [r for r in results if r.metrics.get("done_reason") == "length"]
    return {
        "length_limited": len(limited),
        "empty_length_limited": sum(r.status == "empty" for r in limited),
        "empty_other_or_unknown": sum(
            r.status == "empty" and r.metrics.get("done_reason") != "length" for r in results
        ),
        "finish_reason_recorded": sum(
            r.metrics.get("done_reason") in ("stop", "length") for r in results
        ),
    }


def timing_summary(results: list, recent: list, total: int, status: str) -> dict:
    """Predict remaining answer work only, never a wall-clock completion deadline."""
    import math
    import statistics

    values = [r.latency_seconds for r in recent]
    valid = bool(values) and all(math.isfinite(v) and v > 0 for v in values)
    average = statistics.mean(values) if valid else None
    variation = statistics.pstdev(values) / average if average else None
    output = {
        "mean_seconds": statistics.mean(r.latency_seconds for r in results) if results else None,
        "recent_mean_seconds": average,
        "recent_samples": len(values),
        "remaining_answer_seconds": None,
        "coefficient_of_variation": variation,
        "minimum_samples": 10,
        "maximum_cv": 0.35,
        "scope": "直近20件以内の確定結果から推定した回答処理時間。待機列・一時停止・保存時間を除外し、処理中の1問は全時間を見込みます。完了予定時刻ではありません。",
        "reason": None,
    }
    if status != "running":
        output["reason"] = "実行中のランのみ残り時間を推定します"
    elif len(values) < 10:
        output["reason"] = "確定結果が10件未満のため推定しません"
    elif any(r.status in {"error", "timeout", "ungradable"} for r in recent):
        output["reason"] = "直近にエラー・タイムアウト・採点不可があるため推定しません"
    elif not valid or variation is None or variation > 0.35:
        output["reason"] = "直近の回答時間が不安定なため推定しません"
    else:
        assert average is not None
        output["remaining_answer_seconds"] = average * max(0, total - len(results))
        output["reason"] = (
            "直近の平均時間が続くと仮定した参考値です。残りの問題の難しさや回答長によって変わります"
        )
    return output


def response_evidence(results: list, *, backend: str, mode: str) -> dict:
    """Run-local transport evidence, distinct from model identity and capability claims."""
    received = sum(
        r.metrics.get("backend_response_received") is True
        or (mode == "text" and r.status in {"correct", "incorrect", "empty"})
        for r in results
    )
    mock = backend == "mock"
    return {
        "status": "software_diagnostic"
        if mock
        else "response_observed"
        if received
        else "not_observed",
        "response_results": received,
        "scope": "このランの現行結果に保存されたバックエンド応答。正答・モデルの出所・GPUへの処理帰属・未使用機能の対応を保証しません。接続確認時の情報とは区別します。",
        "reason": "Mockのソフトウェア診断です"
        if mock
        else f"このランでバックエンド応答を{received}件確認しました"
        if received
        else "このランにはバックエンド応答を確認できる結果がまだありません",
    }
