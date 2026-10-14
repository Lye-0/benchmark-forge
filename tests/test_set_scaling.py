"""Pre-optimization golden hashes protect allocation, RNG and canonical encoding."""

import pytest

from llm_benchmark.domain import SetConfig, digest
from llm_benchmark.sets import SetUnavailable, _set_digest, build_set

# Stable generator versions: keep independent of intentional reading.evidence updates.
OLD_IDS = ["math.expression", "math.linear", "data.join"]


@pytest.mark.parametrize(
    ("ids", "count", "ratio", "expected"),
    [
        (OLD_IDS, 100, 0, "2a8c2fe7af7b930ee0891e82437b11f525d520583d987dca27373970ceb8ea0d"),
        (OLD_IDS, 1000, 0, "4684b578a7d4c15cd7202c8a60c4b8d883798cbde01816a7302c97dfff61bac9"),
        (OLD_IDS, 100, 0.1, "03ade7326733ad04daac04633d8a738b3de24d5a8b351ce65ab5bcf41955a3dd"),
        (
            ["math.expression"],
            100,
            0,
            "4eff081323df89d45d9f09c161756602d8abe69f692cc133fbd4c0e9b2f32361",
        ),
        (
            ["math.expression"],
            1000,
            0,
            "3b74dba71af05364949edf72235606eef95132c522cf84173d93795b3164928e",
        ),
        (
            ["math.expression"],
            8000,
            0,
            "22033d8046d482ecf6020aa627faa022f9be58b7c8cea126d865fd7467dd8cf3",
        ),
    ],
)
def test_legacy_hash(ids, count, ratio, expected):
    result = build_set(SetConfig(generator_ids=ids, count=count, fixed_ratio=ratio))
    method = result.metadata["generation_quality"]["method"]
    assert _set_digest(result.config, result.problems, result.weights, method) == expected
    current_payload = {
        "config": result.config.model_dump(),
        "problems": [p.model_dump() for p in result.problems],
        "weights": result.weights,
        "profile_version": "Preview v1",
        "grader_version": result.grader_version,
        "quality_method": method,
    }
    assert result.grader_version == "1.1.0"
    assert result.set_hash == digest(current_payload)
    assert result.set_hash != expected
    assert result.set_id == f"set-{result.set_hash[:24]}"


def test_streamed_hash_matches_canonical_payload():
    result = build_set(SetConfig(generator_ids=OLD_IDS, count=100, fixed_ratio=0))
    # Include encoding edge cases without changing the persisted format.
    result.problems[0].features["日本語"] = {"z": -0.0, "a": [None, True, "\n雪"]}
    method = result.metadata["generation_quality"]["method"]
    expected = digest(
        {
            "config": result.config.model_dump(),
            "problems": [p.model_dump() for p in result.problems],
            "weights": result.weights,
            "profile_version": "Preview v1",
            "grader_version": "1.0.0",
            "quality_method": method,
        }
    )
    assert _set_digest(result.config, result.problems, result.weights, method) == expected


def test_fixed_shortage_never_falls_back(monkeypatch):
    monkeypatch.setattr("llm_benchmark.sets.fixed_catalogue", lambda: [])
    with pytest.raises(SetUnavailable, match="固定問題不足"):
        build_set(SetConfig(generator_ids=["math.expression"], count=1, fixed_ratio=1))
