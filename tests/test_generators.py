import itertools
import json

import pytest

from llm_benchmark.adapters import mock_solve
from llm_benchmark.domain import AnswerSpec, SetConfig, digest
from llm_benchmark.generators import REGISTRY, registry_tree
from llm_benchmark.grading import grade
from llm_benchmark.sets import SetUnavailable, build_set, fixed_catalogue, presets


@pytest.mark.parametrize("generator", list(REGISTRY))
def test_reproducibility_reference_and_public_boundary(generator):
    g = REGISTRY[generator]
    for difficulty, seed in itertools.product([0, 19.3, 50, 81.7, 100], range(8)):
        p = g.generate(seed, difficulty)
        assert p == g.generate(seed, difficulty)
        assert grade(mock_solve(p.prompt), p.answer_spec).correct
        assert set(p.public().model_dump()) == {"problem_id", "prompt"}
        assert "answer_spec" not in p.prompt
        assert "expected" not in p.prompt


def test_fixed_catalogue_integrity_and_reference():
    fixed = fixed_catalogue()
    assert len(fixed) == 20 * len(REGISTRY)
    assert {p.generator_id for p in fixed} == set(REGISTRY)
    for p in fixed:
        g = REGISTRY[p.generator_id]
        assert p == g.generate(p.seed, p.target_difficulty, "fixed")
        assert grade(mock_solve(p.prompt), p.answer_spec).correct


def test_boolean_has_unique_solution():
    for seed in range(8):
        p = REGISTRY["logic.boolean"].generate(seed, 100)
        data = json.loads(p.prompt.split("入力(JSON):\n")[1].splitlines()[0])
        solutions = [
            list(values)
            for values in itertools.product([False, True], repeat=data["count"])
            if values[0] == data["first"]
            and all(
                (a != b) == xor
                for a, b, xor in zip(values[:-1], values[1:], data["xor"], strict=True)
            )
        ]
        assert solutions == [p.answer_spec.expected]


@pytest.mark.parametrize(
    "id,feature",
    [
        ("math.expression", "operations"),
        ("logic.boolean", "variables"),
        ("code.trace", "iterations"),
        ("data.aggregate", "rows"),
        ("temporal.offset", "updates"),
    ],
)
def test_difficulty_controls_grow(id, feature):
    values = [REGISTRY[id].generate(14, d).features[feature] for d in [0, 10.5, 40, 70.2, 100]]
    assert values == sorted(values)
    assert values[-1] > values[0]


def test_frozen_set_is_reproducible_balanced_and_deduplicated():
    config = SetConfig(generator_ids=list(REGISTRY), count=100)
    a, b = build_set(config), build_set(config)
    assert a.set_hash == b.set_hash
    assert [p.model_dump() for p in a.problems] == [p.model_dump() for p in b.problems]
    assert sum(p.origin == "fixed" for p in a.problems) == 50
    assert len({digest(p.prompt) for p in a.problems}) == 100
    assert sum(a.weights.values()) == pytest.approx(1)
    for category in {p.category_id for p in a.problems}:
        assert sum(
            a.weights[p.problem_id] for p in a.problems if p.category_id == category
        ) == pytest.approx(1 / len({g.category_id for g in REGISTRY.values()}))
    assert a.set_hash != build_set(config.model_copy(update={"seed": 99})).set_hash


def test_missing_fixed_items_never_substitute():
    with pytest.raises(SetUnavailable, match="固定問題不足"):
        build_set(SetConfig(generator_ids=["math.linear"], count=30, fixed_ratio=1))
    with pytest.raises(SetUnavailable, match="固定問題不足"):
        build_set(
            SetConfig(
                generator_ids=["math.linear"],
                count=1,
                difficulty_min=10,
                difficulty_max=11,
                fixed_ratio=1,
            )
        )


def test_registry_and_preview_presets():
    tree = registry_tree()
    assert len(tree) == 16
    assert sum(len(s["generators"]) for c in tree for s in c["subcategories"]) == len(REGISTRY)
    assert tree[11]["status"] == "unavailable"
    for preset in presets():
        assert build_set(SetConfig.model_validate(preset["config"])).profile_version == "Preview v1"
    with pytest.raises(SetUnavailable, match="Standard"):
        build_set(
            SetConfig(generator_ids=list(REGISTRY), count=len(REGISTRY), profile="Standard v1")
        )


@pytest.mark.parametrize(
    "patch",
    [
        {"generator_ids": []},
        {"generator_ids": ["math.linear", "math.linear"]},
        {"difficulty_min": 80, "difficulty_max": 10},
        {"difficulty_min": float("nan")},
        {"fixed_ratio": 1.1},
    ],
)
def test_invalid_config(patch):
    with pytest.raises(ValueError):
        SetConfig.model_validate({"generator_ids": ["math.linear"], **patch})


@pytest.mark.parametrize(
    "answer,spec,correct",
    [
        ("2.50000001", AnswerSpec(expected=2.5, type="number", tolerance=1e-7), True),
        ("NaN", AnswerSpec(expected=0, type="number"), False),
        ("1e100000", AnswerSpec(expected=1, type="number"), False),
        ("1e1000000", AnswerSpec(expected=1, type="number"), False),
        ("-1e999999999", AnswerSpec(expected=1, type="number"), False),
        ("答えは3", AnswerSpec(expected=3, type="number"), False),
        ('{"a":1,"a":2}', AnswerSpec(expected={"a": 2}, type="json"), False),
        ('{"a":true}', AnswerSpec(expected={"a": 1}, type="json"), False),
        ('{"b":2,"a":1}', AnswerSpec(expected={"a": 1, "b": 2}, type="json"), True),
        ('{"a":NaN}', AnswerSpec(expected={"a": 0}, type="json"), False),
        ("1 | 2", AnswerSpec(expected="1|2", type="text"), False),
    ],
)
def test_grading_contract(answer, spec, correct):
    assert grade(answer, spec).correct is correct


def test_join_schema_version_preserves_existing_frozen_sets(store):
    from pathlib import Path

    from llm_benchmark.domain import FrozenSet
    from llm_benchmark.runner import comparison, summarize

    legacy = FrozenSet.model_validate_json(
        (Path(__file__).parent / "fixtures" / "legacy_join_set.json").read_text(encoding="utf-8")
    )
    store.save_set(legacy)
    current = build_set(legacy.config)
    store.save_set(current)
    assert current.set_hash != legacy.set_hash
    assert store.get_set(legacy.set_id) == legacy
    assert {p.generator_version for p in legacy.problems} == {"1.0.0"}
    assert {p.generator_version for p in current.problems} == {"1.1.0"}
    for old, new in zip(legacy.problems, current.problems, strict=True):
        assert old.answer_spec == new.answer_spec
        assert old.seed == new.seed
        assert old.content_hash != new.content_hash
        assert "商品idをキー" in new.prompt
        assert grade(mock_solve(new.prompt), new.answer_spec).correct
    reports = [
        summarize(store, store.create_run(s.set_id, store.get_model("mock-reference")))
        for s in (legacy, current)
    ]
    assert not comparison(reports)["comparable"]
