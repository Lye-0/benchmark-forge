import random

import pytest

from llm_benchmark.generators_systems import infer, register_systems, round_robin, schema_valid
from llm_benchmark.mock_systems import solve

BUILDERS = {}


def register(identifier, *metadata):
    def decorator(builder):
        BUILDERS[identifier] = builder
        return builder

    return decorator


register_systems(register, lambda d, lo, hi: lo + round((hi - lo) * d / 100))


@pytest.mark.parametrize("identifier", BUILDERS)
@pytest.mark.parametrize("difficulty", [0, 21.5, 50, 78.3, 100])
def test_independent_reference_and_reproducibility(identifier, difficulty):
    for seed in range(30):
        builder = BUILDERS[identifier]
        first = builder(random.Random(seed), difficulty)
        assert first == builder(random.Random(seed), difficulty)
        data, expected, instruction, features = first
        assert solve(identifier, data) == expected
        assert instruction and features


@pytest.mark.parametrize(
    "identifier,feature",
    [
        ("cs.round_robin", "processes"),
        ("cs.routing", "routes"),
        ("cs.permissions", "requests"),
        ("data.schema", "records"),
        ("data.antijoin", "left_rows"),
        ("code.types", "max_depth"),
        ("code.bug_tests", "cases"),
        ("temporal.intersections", "people"),
    ],
)
def test_difficulty_features(identifier, feature):
    values = [BUILDERS[identifier](random.Random(12), d)[3][feature] for d in [0, 25, 50, 75, 100]]
    assert values == sorted(values)
    assert values[-1] > values[0]


def test_round_robin_boundary_arrivals_and_idle():
    jobs = [
        {"id": "A", "arrival": 0, "burst": 4},
        {"id": "C", "arrival": 2, "burst": 1},
        {"id": "B", "arrival": 2, "burst": 1},
        {"id": "D", "arrival": 10, "burst": 1},
    ]
    expected = {"B": 3, "C": 4, "A": 6, "D": 11}
    assert round_robin(jobs, 2) == expected
    assert solve("cs.round_robin", {"processes": jobs, "quantum": 2}) == expected


def test_routing_longest_prefix_and_first_tie():
    assert solve(
        "cs.routing",
        {
            "routes": [
                {"cidr": "0.0.0.0/0", "next_hop": "default"},
                {"cidr": "10.0.0.0/8", "next_hop": "first"},
                {"cidr": "10.0.0.0/8", "next_hop": "second"},
                {"cidr": "10.1.2.3/32", "next_hop": "host"},
            ],
            "destinations": ["10.1.2.3", "10.1.2.4", "255.255.255.255"],
        },
    ) == ["host", "first", "default"]


def test_permissions_owner_does_not_fall_back():
    assert solve(
        "cs.permissions",
        {
            "files": [{"owner": "u", "group": "g", "mode": [0, 7, 7]}],
            "requests": [
                {"file": 0, "user": "u", "groups": ["g"], "need": 1},
                {"file": 0, "user": "v", "groups": ["g"], "need": 7},
            ],
        },
    ) == [False, True]


def test_schema_rejects_booleans_and_validates_optional_fields():
    rule = {"type": "integer", "minimum": 0, "maximum": 2}
    assert schema_valid(0, rule) and schema_valid(2, rule)
    assert not schema_valid(True, rule)
    assert not schema_valid(None, rule)
    assert not schema_valid(3, rule)
    data, _, _, _ = BUILDERS["data.schema"](random.Random(1), 0)
    rule = data["schema"]
    records = [{"count": 0, "tags": ["red"]}, {"count": 0, "tags": ["red"], "active": 1}]
    assert [schema_valid(row, rule) for row in records] == [True, False]
    assert solve("data.schema", {"schema": rule, "records": records}) == [0]


def test_antijoin_null_and_duplicates():
    assert solve(
        "data.antijoin",
        {
            "left": [
                {"id": 0, "a": None, "b": "x"},
                {"id": 1, "a": 1, "b": "x"},
                {"id": 2, "a": 2, "b": "x"},
            ],
            "right": [
                {"a": None, "b": "x", "enabled": True},
                {"a": 1, "b": "x", "enabled": True},
                {"a": 1, "b": "x", "enabled": True},
                {"a": 2, "b": "x", "enabled": False},
            ],
        },
    ) == [0, 2]


def test_static_type_error_in_any_branch():
    environment = {"p": "bool", "x": "int"}
    expressions = [["if", "p", "x", ["add", "x", "p"]], ["eq", "p", "p"], ["if", "p", "x", "x"]]
    assert [infer(expr, environment) for expr in expressions] == ["error", "bool", "int"]
    assert solve("code.types", {"environment": environment, "expressions": expressions}) == [
        "error",
        "bool",
        "int",
    ]


def test_mutant_boundary_discrimination():
    assert solve(
        "code.bug_tests",
        {
            "lower": 2,
            "upper": 4,
            "cases": [1, 2, 3, 4],
            "variants": ["lower_strict", "upper_inclusive", "disjunction", "reversed"],
        },
    ) == {
        "lower_strict": [1],
        "upper_inclusive": [3],
        "disjunction": [0, 3],
        "reversed": [1, 2],
    }


@pytest.mark.parametrize(
    "schedules,expected",
    [
        ([[[0, 2]], [[2, 4]]], []),
        ([[[0, 2], [2, 5], [1, 3]], [[1, 4]]], [[1, 4]]),
        ([[[0, 8]], [[1, 3], [5, 7]]], [[1, 3], [5, 7]]),
    ],
)
def test_interval_edges(schedules, expected):
    assert solve("temporal.intersections", {"schedules": schedules}) == expected


def test_type_generation_has_valid_and_invalid_examples():
    for difficulty in [0, 50, 100]:
        for seed in range(10):
            _, expected, _, _ = BUILDERS["code.types"](random.Random(seed), difficulty)
            assert set(expected) == {"int", "bool", "error"}
