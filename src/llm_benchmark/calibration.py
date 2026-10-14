"""Descriptive multi-model observations, not calibrated item difficulties."""

from collections import Counter

from llm_benchmark.analysis import calibration_rows
from llm_benchmark.domain import digest
from llm_benchmark.runner import comparison


def analyze_calibration(reports: list[dict]) -> dict:
    if not 2 <= len(reports) <= 10:
        raise ValueError("同じセットの実モデルの完了ランを2〜10件選んでください")
    if len({r["id"] for r in reports}) != len(reports):
        raise ValueError("同じランを重複して指定できません")
    observations = [calibration_rows(report) for report in reports]
    compared = comparison(reports)
    if not compared["comparable"]:
        raise ValueError("問題セット・採点器・回答分離方式が一致するランが必要です")
    identities = [
        digest({k: r["model"].get(k) for k in ("backend", "model", "revision", "quantization")})
        for r in reports
    ]
    if len(set(identities)) != len(identities):
        raise ValueError(
            "同じモデルの再実行や設定違いは別モデルとして集計できません。1件を選んでください"
        )
    reference = reports[0]
    items = []
    expected_ids = [row["problem_id"] for row in observations[0]]
    if len(set(expected_ids)) != len(expected_ids) or len(expected_ids) != reference["total"]:
        raise ValueError("結果に重複または欠落があります")
    for report, rows in zip(reports, observations, strict=True):
        if report["status"] != "completed" or len(rows) != report["total"]:
            raise ValueError("全問題の結果が確定したランが必要です")
        if [row["problem_id"] for row in rows] != expected_ids:
            raise ValueError("問題の実体または順序が一致しません")
    for index, first in enumerate(observations[0]):
        rows = [group[index] for group in observations]
        fields = ("generator_id", "generator_version", "category_id", "target_difficulty")
        if any(any(row[k] != first[k] for k in fields) for row in rows):
            raise ValueError("問題の版または難易度情報が一致しません")
        statuses = Counter(row["status"] for row in rows)
        correct = sum(row["correct"] for row in rows)
        items.append(
            {
                **{k: first[k] for k in ("problem_id", *fields)},
                "observations": len(rows),
                "correct": correct,
                "observed_accuracy": correct / len(rows),
                "status_counts": dict(statuses),
                "empirical_difficulty": None,
            }
        )
    bins = []
    for lower in range(0, 100, 10):
        members = [
            p
            for p in items
            if lower <= p["target_difficulty"] < lower + 10
            or lower == 90
            and p["target_difficulty"] == 100
        ]
        count = sum(p["observations"] for p in members)
        correct = sum(p["correct"] for p in members)
        bins.append(
            {
                "lower": lower,
                "upper": lower + 10,
                "items": len(members),
                "observations": count,
                "correct": correct,
                "observed_accuracy": correct / count if count else None,
            }
        )
    warnings = list(compared["warnings"])
    warnings.extend(
        [
            "選択したモデル群・設定に限定した記述統計です。モデルの独立性や母集団への代表性は保証しません。",
            "再試行は最終結果だけを1件と数えます。エラー・タイムアウト・無回答・採点不可も分母に含みます。",
            "モデル名・登録情報による重複検査です。別名や別バックエンドが同一重みを指す場合は手動で1件に絞ってください。",
            "実測難易度は未校正です。正答率の逆数や補数を難易度へ自動変換せず、正式Standardを発行しません。",
        ]
    )
    if any(row["attempt_count"] > 1 for rows in observations for row in rows):
        warnings.append("再試行を含みます。最終結果の採用による選択バイアスに注意してください。")
    return {
        "method": "selected-model-observations-v1",
        "calibrated": False,
        "set_hash": reference["set_hash"],
        "grader_version": reference["grader_version"],
        "run_ids": [r["id"] for r in reports],
        "model_count": len(reports),
        "item_count": len(items),
        "category_count": len({p["category_id"] for p in items}),
        "conditions": [
            {
                "run_id": r["id"],
                "model": r["model"],
                "environment": r["environment"],
                "response_text_policies": r.get("response_text_policies", []),
                "visibility": r["set_metadata"].get("visibility", "public"),
            }
            for r in reports
        ],
        "by_difficulty": bins,
        "items": items,
        "warnings": warnings,
    }
