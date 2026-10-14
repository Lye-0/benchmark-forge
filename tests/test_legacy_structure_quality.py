import json

import pytest

from llm_benchmark.adapters import mock_solve
from llm_benchmark.generators import REGISTRY
from llm_benchmark.grading import grade


def payload(problem):
    return json.loads(problem.prompt.split("入力(JSON):\n")[1].splitlines()[0])


@pytest.mark.parametrize("identifier", ["code.debug", "tool.select"])
@pytest.mark.parametrize("difficulty", [0, 20, 50, 80, 100])
def test_expanded_legacy_reproducible_and_graded(identifier, difficulty):
    generator = REGISTRY[identifier]
    assert generator.version == "1.1.0"
    for seed in range(100):
        problem = generator.generate(seed, difficulty)
        assert problem == generator.generate(seed, difficulty)
        assert grade(mock_solve(problem.prompt), problem.answer_spec).correct


def test_debug_independent_pointwise_uniqueness():
    for difficulty in [0, 50, 100]:
        for seed in range(60):
            problem = REGISTRY["code.debug"].generate(seed, difficulty)
            data = payload(problem)
            spec = data["contract"]
            matching = []
            for label, candidate in data["options"].items():
                correct = True
                for a, b in data["cases"]:
                    for x in range(a - 4, b + 5):
                        target = (
                            (x >= a if spec["lower_inclusive"] else x > a)
                            and (x <= b if spec["upper_inclusive"] else x < b)
                            and (x - a - int(not spec["lower_inclusive"])) % spec["step"] == 0
                            and all(x % m != v for m, v in spec["exclude"])
                        )
                        actual = (
                            a + candidate["start_offset"] <= x < b + candidate["stop_offset"]
                            and (x - a - candidate["start_offset"]) % candidate["step"] == 0
                            and all(x % m != v for m, v in candidate["exclude"])
                        )
                        if target != actual:
                            correct = False
                if correct:
                    matching.append(label)
            assert matching == [problem.answer_spec.expected]


def test_tool_constraint_and_missing_argument_decoys():
    for difficulty in [0, 50, 100]:
        problem = REGISTRY["tool.select"].generate(41, difficulty)
        data = payload(problem)
        valid = [
            name
            for name, api in data["tools"].items()
            if api["attributes"] == data["constraints"]
            and all(key in data["available_arguments"] for key in api["required"])
        ]
        assert valid == [problem.answer_spec.expected["name"]]
        assert any(
            api["attributes"] == data["constraints"] and "unavailable_token" in api["required"]
            for api in data["tools"].values()
        )
        assert len(problem.answer_spec.expected["arguments"]) == problem.features["argument_count"]


@pytest.mark.parametrize(
    "identifier,feature",
    [
        ("code.debug", "conditions"),
        ("code.debug", "options"),
        ("tool.select", "constraints"),
        ("tool.select", "argument_count"),
    ],
)
def test_structural_difficulty_increases(identifier, feature):
    values = [REGISTRY[identifier].generate(123, d).features[feature] for d in [0, 25, 50, 75, 100]]
    assert values == sorted(values)
    assert values[-1] > values[0]


@pytest.mark.parametrize("identifier", ["code.debug", "tool.select"])
def test_easy_generation_has_broad_domain(identifier):
    prompts = [REGISTRY[identifier].generate(seed, 0).prompt for seed in range(200)]
    assert len(set(prompts)) == 200


def test_legacy_payloads_remain_solvable():
    assert (
        mock_solve(
            '課題: code.debug\n入力(JSON):\n{"n":3,"options":{"A":"range(0, n)","B":"range(1, n + 1)"}}'
        )
        == "B"
    )
    assert json.loads(
        mock_solve('課題: tool.select\n入力(JSON):\n{"item_id":"old-item","tools":{}}')
    ) == {"name": "inventory.lookup", "arguments": {"item_id": "old-item"}}
