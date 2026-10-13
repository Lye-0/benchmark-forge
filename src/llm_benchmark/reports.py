import csv
import io
import json


def export_report(report: dict, format: str) -> tuple[str, str]:
    if format == "jsonl":
        header = {k: v for k, v in report.items() if k not in {"results", "attempts"}}
        lines = [json.dumps({"type": "run", **header}, ensure_ascii=False)]
        lines.extend(
            json.dumps({"type": "result", **r}, ensure_ascii=False) for r in report["results"]
        )
        lines.extend(
            json.dumps({"type": "attempt", **a}, ensure_ascii=False)
            for a in report.get("attempts", [])
        )
        return "\n".join(lines) + "\n", "application/x-ndjson"
    if format == "csv":
        output = io.StringIO()
        fields = [
            "problem_id",
            "category_id",
            "origin",
            "difficulty",
            "status",
            "answer",
            "reason",
            "latency_seconds",
            "metrics",
        ]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for result in report["results"]:
            problem = result["problem"]
            row = {
                **{
                    k: result[k]
                    for k in ["problem_id", "status", "answer", "reason", "latency_seconds"]
                },
                "metrics": json.dumps(result.get("metrics", {}), ensure_ascii=False),
                "category_id": problem["category_id"],
                "origin": problem["origin"],
                "difficulty": problem["target_difficulty"],
            }
            # Prevent formula execution if imported into a spreadsheet.
            for key, value in row.items():
                if isinstance(value, str) and value.lstrip().startswith(
                    ("=", "+", "-", "@", "\t", "\r")
                ):
                    row[key] = "'" + value
            writer.writerow(row)
        return output.getvalue(), "text/csv"
    if format == "markdown":
        model = report.get("model", {})
        counts = report.get("status_counts", {})
        diagnostics = report.get("output_diagnostics", {})
        lines = [
            "# Benchmark Forge / Preview",
            "",
            f"Run: `{report['id']}`",
            f"Set SHA-256: `{report['set_hash']}`",
            "",
            f"カテゴリ均等正答率: {report['accuracy']:.1%}",
            f"処理数: {report['completed']} / {report['total']}",
            f"Mock診断: {'はい（モデル性能ではありません）' if report['test_only'] else 'いいえ'}",
            "",
            "モデル・推論条件:",
            "```json",
            json.dumps(
                {
                    k: model.get(k)
                    for k in (
                        "name",
                        "backend",
                        "model",
                        "revision",
                        "quantization",
                        "temperature",
                        "max_tokens",
                        "timeout_seconds",
                        "context_length",
                        "streaming",
                        "gpu_sampling",
                        "inference_seed",
                    )
                },
                ensure_ascii=False,
                indent=2,
            ),
            "```",
            "",
            f"実行状態: {report.get('status', 'N/A')} / {'暫定' if report.get('provisional', True) else '確定'}",
            "",
            "| 結果 | 件数 |",
            "|---|---:|",
            *[
                f"| {label} | {counts.get(key, 0)} |"
                for key, label in (
                    ("correct", "正解"),
                    ("incorrect", "誤答"),
                    ("empty", "無回答"),
                    ("timeout", "タイムアウト"),
                    ("error", "実行エラー"),
                    ("ungradable", "採点不可"),
                )
            ],
            "",
            f"出力上限による終了: {diagnostics.get('length_limited', 'N/A')}件 / うち無回答: {diagnostics.get('empty_length_limited', 'N/A')}件",
            "終了理由が記録された結果のみ集計。思考の内容や上限変更後の正答は推定しません。",
            "",
            "| Origin | 正解 | 問題数 | 正答率 |",
            "|---|---:|---:|---:|",
        ]
        timing = report.get("timing")
        if timing:
            timing_lines = ["", "回答処理時間（参考）:"]
            for key, label in (
                ("mean_seconds", "全確定結果の平均"),
                ("recent_mean_seconds", "直近の平均"),
                ("remaining_answer_seconds", "残り回答処理時間の推定"),
            ):
                value = timing.get(key)
                formatted = f"{value:.3f} s" if value is not None else "N/A"
                timing_lines.append(f"- {label}: {formatted}")
            timing_lines.extend([timing["scope"], timing["reason"], ""])
            # Insert before the origin table rather than breaking its rows.
            lines[-2:-2] = timing_lines
        for origin, group in report["by_origin"].items():
            accuracy = f"{group['accuracy']:.1%}" if group["accuracy"] is not None else "N/A"
            lines.append(f"| {origin} | {group['correct']} | {group['total']} | {accuracy} |")
        for title, data in (
            ("問題の生成品質", report.get("set_metadata", {}).get("generation_quality")),
            ("GPU連続計測（ホスト全体）", report.get("resources", {}).get("gpu_sampling")),
        ):
            if data:
                lines += [
                    "",
                    title,
                    "```json",
                    json.dumps(data, ensure_ascii=False, indent=2),
                    "```",
                ]
        observations = report.get("environment", {}).get("model_observations", [])
        if observations:
            lines += [
                "",
                "モデル識別情報（実行区間ごとの観測）:",
                "```json",
                json.dumps(observations, ensure_ascii=False, indent=2),
                "```",
                "バックエンドの申告情報です。重みファイルの直接検証や各回答時点での不変性を保証しません。",
            ]
        lines += ["", *[f"- {warning}" for warning in report["warnings"]]]
        return "\n".join(lines) + "\n", "text/markdown"
    raise ValueError("未対応の出力形式です")


def stream_jsonl(store, run_id: str):
    rows = store.iter_export(run_id)
    try:
        for row in rows:
            yield json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
    finally:
        rows.close()
