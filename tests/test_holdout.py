import json

import pytest
from fastapi.testclient import TestClient

from llm_benchmark.api import create_app
from llm_benchmark.domain import SetConfig
from llm_benchmark.generators import REGISTRY
from llm_benchmark.holdout import import_holdout
from llm_benchmark.sets import build_set


def document():
    problem = REGISTRY["math.linear"].generate(42, 30)
    return "\n".join(
        json.dumps(v)
        for v in [
            {
                "schema": "forge-holdout-v1",
                "name": "Private fixture",
                "source": "original test",
                "license": "private-use",
            },
            {
                "prompt": problem.prompt,
                "category_id": "01",
                "target_difficulty": 30,
                "answer_spec": problem.answer_spec.model_dump(),
            },
        ]
    )


def test_holdout_freezes_reproducibly_and_keeps_provenance():
    a, b = import_holdout(document()), import_holdout(document())
    assert a.set_hash == b.set_hash
    assert a.metadata["visibility"] == "private"
    assert a.problems[0].verification == "experimental"
    assert a.config.fixed_ratio == 1
    assert sum(a.weights.values()) == 1
    assert "answer_spec" not in a.problems[0].public().model_dump()


@pytest.mark.parametrize(
    "bad",
    [
        "{}",
        "{}\n{}",
        "x\nsecret-private-prompt",
        document() + "\n" + document().splitlines()[1],
        document().replace(
            '"type": "number"', '"type": "number", "extra": "secret-private-prompt"'
        ),
        document().replace('"category_id": "01"', '"category_id": "99"'),
        document().replace('"target_difficulty": 30', '"target_difficulty": NaN'),
        document().replace(
            '"target_difficulty": 30', '"target_difficulty": 30, "target_difficulty": 50'
        ),
    ],
)
def test_holdout_rejects_bad_inputs_without_echo(bad):
    with pytest.raises(ValueError) as exc:
        import_holdout(bad)
    assert "secret-private-prompt" not in str(exc.value)


def test_holdout_api_is_local_and_redacts_answers(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1") as client:
        response = client.post("/api/holdouts", json={"jsonl": document()})
        assert response.status_code == 200
        id = response.json()["set_id"]
        public = client.get("/api/sets/" + id)
        assert "answer_spec" not in public.text
        saved = client.app.state.store.get_set(id)
        assert saved.metadata["license"] == "private-use"
        assert (
            client.post(
                "/api/holdouts",
                json={"jsonl": document()},
                headers={"Origin": "https://outside.invalid"},
            ).status_code
            == 403
        )


def test_integer_and_float_difficulty_have_same_identity():
    for g in REGISTRY.values():
        assert g.generate(1, 50) == g.generate(1, 50.0)


def test_large_dynamic_set_is_unique_and_balanced():
    frozen = build_set(
        SetConfig(
            generator_ids=["math.expression", "data.aggregate", "cs.lru"], count=1000, fixed_ratio=0
        )
    )
    assert len({p.problem_id for p in frozen.problems}) == 1000
    assert sum(frozen.weights.values()) == pytest.approx(1)


def test_api_validation_errors_do_not_echo_private_input(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1") as client:
        response = client.post("/api/holdouts", json={"jsonl": ["secret-private-prompt"]})
        assert response.status_code == 422
        assert "secret-private-prompt" not in response.text
