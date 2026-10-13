import json

import pytest

from llm_benchmark.domain import SetConfig, canonical
from llm_benchmark.generators import REGISTRY
from llm_benchmark.quality import UNORDERED, equivalence_key, quality_report
from llm_benchmark.sets import build_set


def with_input(problem, change):
    prefix, body = problem.prompt.split("入力(JSON):\n", 1)
    value, suffix = body.split("\n", 1)
    payload = json.loads(value)
    change(payload)
    return problem.model_copy(
        update={"prompt": prefix + "入力(JSON):\n" + canonical(payload) + "\n" + suffix}
    )


@pytest.mark.parametrize("generator", list(UNORDERED))
def test_reordered_commutative_inputs_are_equivalent(generator):
    p = REGISTRY[generator].generate(14, 80)

    def reverse(payload):
        for key in UNORDERED[generator]:
            payload[key].reverse()

    changed = with_input(p, reverse)
    assert equivalence_key(p) == equivalence_key(changed)


def test_expression_equivalence_preserves_values_and_multiplicity():
    p = REGISTRY["math.expression"].generate(1, 80)
    reordered = with_input(
        p, lambda d: d.update(pairs=[list(reversed(x)) for x in reversed(d["pairs"])])
    )
    assert equivalence_key(p) == equivalence_key(reordered)
    repeated = with_input(p, lambda d: d["pairs"].append(d["pairs"][0]))
    assert equivalence_key(p) != equivalence_key(repeated)
    same_answer = p.model_copy(
        update={"answer_spec": p.answer_spec.model_copy(update={"expected": 999})}
    )
    assert equivalence_key(p) == equivalence_key(same_answer)


def test_order_sensitive_inputs_and_unknown_formats_are_not_normalized():
    p = REGISTRY["dialogue.state"].generate(1, 80)
    reordered = with_input(p, lambda d: d["events"].reverse())
    assert equivalence_key(p) != equivalence_key(reordered)
    malformed = p.model_copy(update={"generator_id": "math.expression", "prompt": "private input"})
    assert equivalence_key(malformed) != equivalence_key(
        malformed.model_copy(update={"prompt": "private  input"})
    )


def test_quality_rates_and_structures_do_not_claim_independent_variants():
    problems = [REGISTRY["math.median"].generate(i, 50) for i in range(3)]
    report = quality_report(problems, surface_rejected=1, semantic_rejected=2)
    assert report["adoption_rate"] == report["duplicate_rate"] == 0.5
    assert report["structures"] == 1
    assert report["repeated_structures"] == 2
    assert report["structure_counts"] == {"order-statistic": 3}


def test_equivalent_dynamic_candidates_are_retried_and_recorded(monkeypatch):
    from dataclasses import replace

    original = REGISTRY["math.median"]
    calls = 0

    def build(r, d):
        nonlocal calls
        calls += 1
        values = [1, 2, 3] if calls == 1 else [3, 2, 1] if calls == 2 else [4, 5, 6]
        return {"values": values}, values[1], "中央値を答えてください。", {"elements": 3}

    monkeypatch.setitem(REGISTRY, original.id, replace(original, build=build))
    frozen = build_set(SetConfig(generator_ids=[original.id], count=2, fixed_ratio=0))
    assert calls == 3
    assert frozen.duplicate_stats["semantic_rejected"] == 1
    assert frozen.metadata["generation_quality"]["adoption_rate"] == pytest.approx(2 / 3)
