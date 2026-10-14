import json
import re

import pytest

from llm_benchmark.adapters import mock_solve
from llm_benchmark.domain import canonical
from llm_benchmark.generators import REGISTRY
from llm_benchmark.grading import grade


@pytest.mark.parametrize("difficulty", [0, 19.3, 50, 81.7, 100])
def test_evidence_ids_are_opaque_and_reference_follows_records(difficulty):
    generator = REGISTRY["reading.evidence"]
    for seed in range(16):
        problem = generator.generate(seed, difficulty)
        assert problem == generator.generate(seed, difficulty)
        assert problem.generator_version == "1.1.0"
        data = json.loads(problem.prompt.split("入力(JSON):\n")[1].splitlines()[0])
        documents = data["documents"]
        ids = [doc["id"] for doc in documents]
        assert len(ids) == len(set(ids))
        assert all(re.fullmatch(r"doc-[0-9a-f]{8}", value) for value in ids)

        # Build independent relations from record text, without assuming ID prefixes,
        # matching numeric suffixes, record ordering, or item positions.
        ownership, storage = {}, {}
        for doc in documents:
            owner = re.fullmatch(r"(人物\d+)の担当品は(品物\d+)。", doc["text"])
            location = re.fullmatch(r"(品物\d+)の保管場所は(倉庫\d+)。", doc["text"])
            if owner:
                ownership[owner[1]] = (owner[2], doc["id"])
            elif location:
                storage[location[1]] = (location[2], doc["id"])
            else:
                pytest.fail("Unexpected evidence record")
        item, owner_id = ownership[data["person"]]
        place, location_id = storage[item]
        assert owner_id.split("-", 1)[1] != location_id.split("-", 1)[1]
        expected = {"place": place, "evidence": [owner_id, location_id]}
        assert problem.answer_spec.expected == expected
        assert grade(mock_solve(problem.prompt), problem.answer_spec).correct


def test_evidence_solver_follows_arbitrary_record_renaming_and_reordering():
    problem = REGISTRY["reading.evidence"].generate(42, 100)
    prefix, body = problem.prompt.split("入力(JSON):\n", 1)
    encoded, suffix = body.split("\n", 1)
    data = json.loads(encoded)
    replacements = {doc["id"]: f"renamed-{index}" for index, doc in enumerate(data["documents"])}
    for doc in data["documents"]:
        doc["id"] = replacements[doc["id"]]
    data["documents"].reverse()
    changed_prompt = prefix + "入力(JSON):\n" + canonical(data) + "\n" + suffix
    expected = {
        "place": problem.answer_spec.expected["place"],
        "evidence": [replacements[key] for key in problem.answer_spec.expected["evidence"]],
    }
    assert json.loads(mock_solve(changed_prompt)) == expected
