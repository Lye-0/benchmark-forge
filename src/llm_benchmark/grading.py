import json
import math
import re
from decimal import Decimal, InvalidOperation

from llm_benchmark.domain import AnswerSpec, Grade, canonical

GRADER_VERSION = "1.0.0"


def grade(answer: str, spec: AnswerSpec) -> Grade:
    text = answer.strip()
    if spec.type == "text":
        # Strict format tasks preserve inner whitespace and casing.
        correct = answer == str(spec.expected)
        return Grade(
            correct=correct, reason="完全一致" if correct else "期待する文字列と不一致", parsed=text
        )
    if spec.type == "number":
        if not re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", text):
            return Grade(correct=False, reason="単一の有限数値が必要です")
        try:
            value = Decimal(text)
            expected = Decimal(str(spec.expected))
            correct = value.is_finite() and abs(value - expected) <= Decimal(str(spec.tolerance))
            parsed = float(value)
            if not math.isfinite(parsed):
                return Grade(correct=False, reason="数値が大きすぎます")
            return Grade(
                correct=correct, reason="許容誤差内" if correct else "数値が不一致", parsed=parsed
            )
        except (InvalidOperation, OverflowError):
            return Grade(correct=False, reason="数値を解釈できません")
    try:

        def no_duplicates(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate key")
                result[key] = value
            return result

        def no_constants(value):
            raise ValueError("non-finite JSON")

        parsed = json.loads(text, object_pairs_hook=no_duplicates, parse_constant=no_constants)
        # Canonical comparison preserves bool vs number, rejects surplus fields, allows key reordering.
        correct = canonical(parsed) == canonical(spec.expected)
        return Grade(
            correct=correct,
            reason="構造化回答が一致" if correct else "JSONの値または型が不一致",
            parsed=parsed,
        )
    except (ValueError, TypeError, RecursionError):
        return Grade(correct=False, reason="有効な重複キーのないJSONが必要です")
