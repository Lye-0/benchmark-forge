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
    output["scope"] = "成功応答のワーカー計測の最大値。失敗時・GPU全体の使用量は含まない"
    return output


def calibration_rows(report: dict) -> list[dict]:
    """Export observations, not fitted or asserted empirical difficulty values."""
    if (
        report["test_only"]
        or report["provisional"]
        or report["profile_version"] == "Speed probe v1"
        or report.get("measurement_kind", "text") != "text"
    ):
        raise ValueError("校正用データには完了した実モデルの能力評価ランが必要です")
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
            "attempt_count": sum(a["idx"] == row["index"] for a in report["attempts"]),
            "visibility": report["set_metadata"].get("visibility", "public"),
        }
        for row in report["results"]
    ]
