"""Independent reference, invariance, and bounded exhaustive reasoning checks."""

import itertools
import random
from fractions import Fraction

import pytest

from llm_benchmark.generators import Generator, size
from llm_benchmark.generators_reasoning import register_reasoning
from llm_benchmark.mock_reasoning import SUPPORTED_IDS, solve


@pytest.fixture(scope="module")
def families():
    registry = {}

    def register(identifier, category, subcategory, name, template, answer_type):
        def wrap(builder):
            registry[identifier] = Generator(
                identifier, category, subcategory, name, template, answer_type, builder
            )
            return builder

        return wrap

    register_reasoning(register, size)
    assert set(registry) == SUPPORTED_IDS
    return registry


@pytest.mark.parametrize("task", sorted(SUPPORTED_IDS))
@pytest.mark.parametrize("difficulty", [0, 37.5, 100])
def test_references_reproduction_and_variation(families, task, difficulty):
    generator = families[task]
    prompts = set()
    for seed in range(25):
        payload, expected, _, features = generator.build(random.Random(seed), difficulty)
        assert solve(task, payload) == expected
        problem = generator.generate(seed, difficulty)
        assert problem == generator.generate(seed, difficulty)
        assert problem.answer_spec.expected == expected
        assert features
        prompts.add(problem.prompt)
    assert len(prompts) >= 20


def test_exhaustive_small_sampling():
    for red, blue in itertools.product(range(1, 5), repeat=2):
        for draws in range(1, red + blue + 1):
            samples = list(itertools.combinations(range(red + blue), draws))
            for target in range(draws + 1):
                good = sum(sum(x < red for x in sample) == target for sample in samples)
                answer = Fraction(good, len(samples))
                assert solve(
                    "math.probability",
                    {"red": red, "blue": blue, "draws": draws, "target_red": target},
                ) == {"numerator": answer.numerator, "denominator": answer.denominator}


def test_exhaustive_three_node_graphs():
    edges = list(itertools.permutations(range(3), 2))
    for bits in itertools.product([False, True], repeat=len(edges)):
        active = [edge for edge, keep in zip(edges, bits, strict=True) if keep]
        for start in range(3):
            expected = {start}
            for path_length in range(1, 3):
                for suffix in itertools.product(range(3), repeat=path_length):
                    path = (start, *suffix)
                    if all((a, b) in active for a, b in zip(path, path[1:], strict=False)):
                        expected.add(path[-1])
            assert solve(
                "algorithm.reachability", {"nodes": 3, "edges": active, "start": start}
            ) == sorted(expected)


def test_cyclic_rules_and_conjunctive_premises():
    data = {
        "atoms": list(range(6)),
        "facts": [0],
        "rules": [[[0], 1], [[1], 0], [[2], 3], [[3], 2], [[0, 2], 4], [[0, 1], 5]],
    }
    assert solve("logic.implication", data) == [0, 1, 5]


def test_exhaustive_minimax_depth_two():
    for leaves in itertools.product([-1, 0, 1], repeat=4):
        expected = max(min(leaves[0], leaves[1]), min(leaves[2], leaves[3]))
        assert solve("algorithm.minimax", {"depth": 2, "leaves": leaves}) == expected


def test_polygon_translation_and_orientation(families):
    for seed in range(20):
        data, expected, _, _ = families["math.polygon_area"].build(random.Random(seed), 100)
        transformed = [[x + 31, y - 72] for x, y in reversed(data["vertices"])]
        assert solve("math.polygon_area", {"vertices": transformed}) == expected


def test_difficulty_changes_structural_work(families):
    for generator in families.values():
        low = generator.build(random.Random(17), 0)[3]
        high = generator.build(random.Random(17), 100)[3]
        assert low != high


def test_unsupported_solver():
    with pytest.raises(ValueError, match="Unsupported"):
        solve("missing", {})


def test_assignment_requires_global_optimization():
    assert solve("planning.assignment", {"costs": [[1, 2], [2, 100]]}) == 4
    assert solve("planning.assignment", {"costs": [[2, 2], [2, 2]]}) == 4


def test_interval_selection_touching_and_greedy_trap():
    assert solve("planning.interval_selection", {"jobs": [[0, 2, 4], [2, 4, 4], [0, 4, 7]]}) == 8
    assert (
        solve(
            "planning.interval_selection", {"jobs": [[0, 4, 20], [0, 1, 2], [1, 2, 3], [2, 4, 4]]}
        )
        == 20
    )


@pytest.mark.parametrize(
    "source,target,expected",
    [
        ("", "abc", 3),
        ("abc", "", 3),
        ("abc", "abc", 0),
        ("ab", "ba", 2),
        ("kitten", "sitting", 3),
        ("aaaa", "a", 3),
    ],
)
def test_edit_distance_operation_contract(source, target, expected):
    assert solve("algorithm.edit_distance", {"source": source, "target": target}) == expected


def test_set_expression_noncommutative_difference():
    sets = {"A": [1, 2], "B": [2, 3]}
    assert solve("logic.set_relations", {"sets": sets, "expression": ["difference", "A", "B"]}) == [
        1
    ]
    assert solve("logic.set_relations", {"sets": sets, "expression": ["difference", "B", "A"]}) == [
        3
    ]
    assert solve("logic.set_relations", {"sets": sets, "expression": ["xor", "A", "B"]}) == [1, 3]


@pytest.mark.parametrize("difficulty", [0, 50, 100])
def test_reachability_requires_multihop_and_direction(families, difficulty):
    for seed in range(1000):
        data, answer, _, features = families["algorithm.reachability"].build(
            random.Random(seed), difficulty
        )
        assert 3 <= len(answer) < data["nodes"]
        distances = {data["start"]: 0}
        frontier = [data["start"]]
        while frontier:
            node = frontier.pop(0)
            for a, b in data["edges"]:
                if a == node and b not in distances:
                    distances[b] = distances[a] + 1
                    frontier.append(b)
        assert max(distances.values()) == features["required_hops"] >= 2
        assert sorted(distances) == answer
        assert any(a not in answer and b in answer for a, b in data["edges"])
