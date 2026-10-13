"""Conservative, versioned equivalence rules over public generator inputs only.

Reordered commutative inputs are duplicates; sharing an answer or a template is
not sufficient. Unknown generators fall back to exact prompt identity.
"""

import json
from collections import Counter

from llm_benchmark.domain import Problem, canonical, digest

VERSION = "input-equivalence-v1"
# Lists whose ordering is explicitly irrelevant to the requested answer.
UNORDERED = {
    "math.median": ("values",),
    "math.crt": ("conditions",),
    "logic.order": ("before",),
    "algorithm.path": ("edges",),
    "algorithm.knapsack": ("items",),
    "data.aggregate": ("rows",),
    "data.join": ("products", "orders"),
    "instruction.format": ("values",),
    "language.scope": ("sentences",),
    "reading.evidence": ("documents",),
    "planning.schedule": ("dependencies",),
    "robust.consistency": ("observations",),
}


def equivalence_key(problem: Problem) -> str:
    """Preserve wording/version and multiplicity; never inspect reference answers."""
    if problem.generator_id not in UNORDERED and problem.generator_id != "math.expression":
        return digest(problem.prompt)
    try:
        prefix, body = problem.prompt.split("入力(JSON):\n", 1)
        data_text, suffix = body.split("\n", 1)
        data = json.loads(data_text)
        if problem.generator_id == "math.expression":
            data["pairs"] = sorted((sorted(pair) for pair in data["pairs"]), key=canonical)
        else:
            for key in UNORDERED[problem.generator_id]:
                data[key] = sorted(data[key], key=canonical)
        return digest([VERSION, problem.generator_version, prefix, data, suffix])
    except (ValueError, KeyError, TypeError):
        # Imported/legacy prompts outside the documented format are never guessed.
        return digest(problem.prompt)


def quality_report(
    problems: list[Problem], *, surface_rejected: int, semantic_rejected: int
) -> dict:
    counts = Counter(p.template for p in problems)
    adopted = len(problems)
    rejected = surface_rejected + semantic_rejected
    attempted = adopted + rejected
    return {
        "method": VERSION,
        "adopted": adopted,
        "candidate_attempts": attempted,
        "surface_rejected": surface_rejected,
        "semantic_rejected": semantic_rejected,
        "adoption_rate": adopted / attempted if attempted else None,
        "duplicate_rate": rejected / attempted if attempted else None,
        "structures": len(counts),
        "repeated_structures": adopted - len(counts),
        "structure_counts": dict(sorted(counts.items())),
        "equivalence_supported_generators": sorted(UNORDERED.keys() | {"math.expression"}),
        "scope": "同一テンプレートの反復は構造数を増やしません。意味的重複の除外は、対応する生成器の順序不変な入力の並べ替えに限定します。名前変更・一般的な意味同値は未判定です。採択率の分母は選択候補と動的生成試行で、固定銀行全件の走査数ではありません。",
    }
