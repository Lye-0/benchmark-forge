import json
import math
import re
from decimal import Decimal, DecimalException

from llm_benchmark.domain import AnswerSpec, Grade, canonical

GRADER_VERSION = "1.1.0"


def _json_equal(actual, expected) -> bool:
    """Compare JSON values without rounding numbers or equating booleans with 0/1."""
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    numeric = (int, float, Decimal)
    if isinstance(actual, numeric) and isinstance(expected, numeric):
        left, right = Decimal(str(actual)), Decimal(str(expected))
        return left.is_finite() and right.is_finite() and left == right
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            _json_equal(actual[key], expected[key]) for key in actual
        )
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _json_equal(a, b) for a, b in zip(actual, expected, strict=True)
        )
    return type(actual) is type(expected) and actual == expected


def grade(answer: str, spec: AnswerSpec, grader_version: str = GRADER_VERSION) -> Grade:
    if grader_version not in {"1.0.0", "1.1.0"}:
        raise ValueError(f"Unsupported grader version: {grader_version}")
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
        except (DecimalException, OverflowError):
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

        if grader_version == "1.0.0":
            parsed = json.loads(text, object_pairs_hook=no_duplicates, parse_constant=no_constants)
            # Preserve the historical lexical numeric comparison for frozen sets.
            correct = canonical(parsed) == canonical(spec.expected)
        else:
            # Decimal parsing preserves fractional/exponent spellings of large integers.
            parsed = json.loads(
                text,
                object_pairs_hook=no_duplicates,
                parse_constant=no_constants,
                parse_float=Decimal,
            )
            correct = _json_equal(parsed, spec.expected)
        return Grade(
            correct=correct,
            reason="構造化回答が一致" if correct else "JSONの値または型が不一致",
            parsed=parsed,
        )
    except (ValueError, TypeError, RecursionError, DecimalException):
        return Grade(correct=False, reason="有効な重複キーのないJSONが必要です")
