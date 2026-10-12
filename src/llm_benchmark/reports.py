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
            "| Origin | 正解 | 問題数 | 正答率 |",
            "|---|---:|---:|---:|",
        ]
        for origin, group in report["by_origin"].items():
            accuracy = f"{group['accuracy']:.1%}" if group["accuracy"] is not None else "N/A"
            lines.append(f"| {origin} | {group['correct']} | {group['total']} | {accuracy} |")
        lines += ["", *[f"- {warning}" for warning in report["warnings"]]]
        return "\n".join(lines) + "\n", "text/markdown"
    raise ValueError("未対応の出力形式です")
