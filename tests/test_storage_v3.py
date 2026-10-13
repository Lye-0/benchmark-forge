import json
import sqlite3
import tracemalloc

import pytest
from fastapi.testclient import TestClient

from llm_benchmark.api import create_app
from llm_benchmark.domain import Result
from llm_benchmark.runner import summarize
from llm_benchmark.storage import Store


def make_v2(store, frozen):
    with sqlite3.connect(store.path) as con:
        con.execute("UPDATE sets SET data=? WHERE id=?", (frozen.model_dump_json(), frozen.set_id))
        con.execute("DROP TABLE set_items")
        con.execute("PRAGMA user_version=2")


def test_v2_split_preserves_all_frozen_data_and_runs(store, frozen):
    id = store.create_run(frozen.set_id, store.get_model("mock-reference"))
    make_v2(store, frozen)
    restored = Store(store.path.parent)
    assert restored.get_set(frozen.set_id) == frozen
    assert restored.run(id)["set_id"] == frozen.set_id
    with restored.connection() as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 3
        assert con.execute("SELECT json_type(data,'$.problems') FROM sets").fetchone()[0] is None
        assert con.execute("SELECT count(*) FROM set_items").fetchone()[0] == len(frozen.problems)
    restored.save_set(frozen.model_copy(update={"warnings": ["must not overwrite"]}))
    assert Store(store.path.parent).get_set(frozen.set_id) == frozen


def test_failed_migration_rolls_back_schema_and_original_payload(store, frozen):
    make_v2(store, frozen)
    with sqlite3.connect(store.path) as con:
        con.execute(
            "CREATE TRIGGER deny_split BEFORE UPDATE ON sets BEGIN SELECT RAISE(ABORT, 'fixture failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        Store(store.path.parent)
    with sqlite3.connect(store.path) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 2
        assert con.execute("SELECT data FROM sets").fetchone()[0] == frozen.model_dump_json()
        assert not con.execute("SELECT name FROM sqlite_master WHERE name='set_items'").fetchall()
        con.execute("DROP TRIGGER deny_split")
    assert Store(store.path.parent).get_set(frozen.set_id) == frozen


def test_paged_logs_filter_all_rows_and_include_matching_attempts(store, frozen):
    id = store.create_run(frozen.set_id, store.get_model("mock-reference"))
    for index, problem in enumerate(frozen.problems):
        store.save_result(
            id,
            Result(
                index=index,
                problem_id=problem.problem_id,
                status="correct" if index % 2 == 0 else "empty",
                correct=index % 2 == 0,
                answer=f"answer-{index}",
                reason="fixture",
                latency_seconds=1,
            ),
        )
    with TestClient(create_app(store.path.parent), base_url="http://127.0.0.1") as client:
        first = client.get(f"/api/runs/{id}/results?limit=3&status=empty").json()
        second = client.get(f"/api/runs/{id}/results?limit=3&status=empty&offset=3").json()
        assert first["total"] == 10
        assert [r["index"] for r in first["results"]] == [1, 3, 5]
        assert [r["index"] for r in second["results"]] == [7, 9, 11]
        assert [a["idx"] for a in second["attempts"]] == [7, 9, 11]
        assert second["results"][0]["problem"] == frozen.problems[7].model_dump()
        assert client.get(f"/api/runs/{id}/results?limit=101").status_code == 422
        assert client.get(f"/api/runs/{id}/results?offset=-1").status_code == 422
        assert client.get(f"/api/runs/{id}/results?status=bogus").status_code == 422
        assert client.get("/api/runs/missing/results").status_code == 404
        compact = client.get(f"/api/runs/{id}?detail=false").json()
        assert "results" not in compact and "attempts" not in compact
        assert "config" in compact
    full = summarize(store, id)
    assert compact["accuracy"] == full["accuracy"]
    assert compact["by_difficulty"] == full["by_difficulty"]
    assert full["results"][7]["answer"] == "answer-7"


def test_archive_and_summary_do_not_materialize_large_problem_payloads(store, frozen):
    # 6 MB of prompt data; the iterator must retain only the current row.
    count = 400
    problems = [
        frozen.problems[0].model_copy(update={"problem_id": f"p-{i}", "prompt": "x" * 16000})
        for i in range(count)
    ]
    large = frozen.model_copy(
        update={
            "set_id": "set-" + "e" * 24,
            "problems": problems,
            "weights": {p.problem_id: 1 / count for p in problems},
        }
    )
    store.save_set(large)
    id = store.create_run(large.set_id, store.get_model("mock-reference"))
    tracemalloc.start()
    try:
        rows = 0
        for row in store.iter_export(id):
            json.dumps(row)
            rows += 1
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert rows == count + 1
    assert peak < 2_000_000
    metadata = store.get_set(large.set_id, metadata_only=True)
    assert all(not p.prompt and p.answer_spec.expected is None for p in metadata.problems)
    assert store.get_set(large.set_id).problems == problems


def test_legacy_optional_header_defaults_survive_stream_export(store, frozen):
    legacy = frozen.model_dump()
    for key in ("metadata", "grader_version", "profile_version"):
        legacy.pop(key)
    make_v2(store, frozen)
    with sqlite3.connect(store.path) as con:
        con.execute("UPDATE sets SET data=?", (json.dumps(legacy),))
    restored = Store(store.path.parent)
    id = restored.create_run(frozen.set_id, restored.get_model("mock-reference"))
    rows = list(restored.iter_export(id))
    assert rows[0]["set_metadata"] == {}
    assert rows[0]["grader_version"] == "1.0.0"
    assert restored.set_header(frozen.set_id)["metadata"] == {}
