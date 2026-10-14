import json

import pytest

from llm_benchmark.domain import AnswerSpec, FrozenSet, Response, SetConfig
from llm_benchmark.grading import GRADER_VERSION, grade
from llm_benchmark.runner import Scheduler, comparison, summarize
from llm_benchmark.sets import _set_digest, build_set


@pytest.mark.parametrize(
    "answer,expected,correct",
    [
        ('{"a":1.0,"b":[2e0,-0.0]}', {"b": [2, 0], "a": 1}, True),
        ('{"a":9007199254740993.0}', {"a": 9007199254740993}, True),
        ('{"a":9007199254740992.0}', {"a": 9007199254740993}, False),
        ('{"a":9007199254740993}', {"a": 9007199254740993}, True),
        ('{"a":1.0000000000000000000000000001}', {"a": 1}, False),
        ('{"a":0.10000000000000001}', {"a": 0.1}, False),
        ('{"a":true}', {"a": 1}, False),
        ('{"a":0}', {"a": False}, False),
        ('{"a":"1"}', {"a": 1}, False),
        ('{"a":1,"b":0}', {"a": 1}, False),
        ('{"a":1,"a":1}', {"a": 1}, False),
        ('{"a":NaN}', {"a": 1}, False),
        ('{"a":Infinity}', {"a": 1}, False),
        ('{"a":-Infinity}', {"a": 1}, False),
        ('{"a":[2,1]}', {"a": [1, 2]}, False),
        ('{"a":[1,2,3]}', {"a": [1, 2]}, False),
        ('{"a":null}', {"a": None}, True),
        ('{"a":1e9999999999999999999999}', {"a": 1}, False),
    ],
)
def test_numeric_json_equivalence_is_exact_and_structurally_strict(answer, expected, correct):
    assert grade(answer, AnswerSpec(type="json", expected=expected)).correct is correct


def test_legacy_grader_keeps_historical_numeric_spellings_and_unknown_versions_fail():
    spec = AnswerSpec(type="json", expected={"a": 1})
    assert GRADER_VERSION == "1.1.0"
    assert grade('{"a":1.0}', spec, "1.1.0").correct
    assert not grade('{"a":1.0}', spec, "1.0.0").correct
    for version in ("1.0.0", "1.1.0"):
        assert grade('{"a":1}', spec, version).correct
        assert not grade("1e1000000", AnswerSpec(type="number", expected=1), version).correct
    with pytest.raises(ValueError, match="Unsupported grader version"):
        grade('{"a":1}', spec, "99.0.0")


async def test_saved_legacy_sets_regrade_with_original_rules_and_are_not_comparable(
    store, monkeypatch
):
    current = build_set(SetConfig(generator_ids=["data.aggregate"], count=1, fixed_ratio=0))
    method = current.metadata["generation_quality"]["method"]
    old_hash = _set_digest(current.config, current.problems, current.weights, method)
    legacy_data = current.model_dump()
    legacy_data.pop("grader_version")  # Historical data without the field keeps its old default.
    legacy_data.update(set_id=f"set-{old_hash[:24]}", set_hash=old_hash)
    legacy = FrozenSet.model_validate(legacy_data)
    assert legacy.grader_version == "1.0.0"
    assert current.grader_version == "1.1.0"
    assert current.set_hash != legacy.set_hash
    for frozen in (legacy, current):
        store.save_set(frozen)
        assert store.get_set(frozen.set_id) == frozen

    response = json.dumps(
        {key: float(value) for key, value in current.problems[0].answer_spec.expected.items()}
    )

    class DecimalAnswerAdapter:
        async def complete(self, problem):
            return Response(text=response)

    monkeypatch.setattr("llm_benchmark.runner.make_adapter", lambda config: DecimalAnswerAdapter())
    scheduler = Scheduler(store)
    scheduler.start()
    try:
        # Re-evaluate the same persisted historical set twice, then evaluate the new set.
        run_ids = [
            scheduler.create(frozen.set_id, ["mock-reference"])[0]
            for frozen in (legacy, legacy, current)
        ]
        await scheduler.queue.join()
        reports = [summarize(store, run_id) for run_id in run_ids]
        assert [report["accuracy"] for report in reports] == [0, 0, 1]
        assert [report["grader_version"] for report in reports] == ["1.0.0", "1.0.0", "1.1.0"]
        assert comparison(reports[:2])["comparable"]
        assert not comparison(reports[1:])["comparable"]
        # Even otherwise-identical report metadata must not bypass the grader-version check.
        same_hash = {**reports[2], "set_hash": reports[1]["set_hash"]}
        assert not comparison([reports[1], same_hash])["comparable"]
    finally:
        await scheduler.close()
