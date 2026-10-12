import json
import time

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from llm_benchmark.api import create_app
from llm_benchmark.cli import app as cli
from llm_benchmark.generators import REGISTRY
from llm_benchmark.reports import export_report


@pytest.fixture
def client(tmp_path):
    with TestClient(
        create_app(tmp_path / "api"), base_url="http://127.0.0.1", backend_options={"debug": True}
    ) as client:
        yield client


def config():
    return {"generator_ids": list(REGISTRY)[:14], "count": 20, "seed": 41, "fixed_ratio": 0.5}


def finish(client, id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = client.get(f"/api/runs/{id}").json()
        if result["status"] == "completed":
            return result
        time.sleep(0.025)
    pytest.fail("Run did not finish")


def test_full_api_flow_set_privacy_sse_compare_export(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert len(client.get("/api/registry").json()["categories"]) == 16
    frozen = client.post("/api/sets", json=config()).json()
    assert frozen["fixed_count"] == 10
    public = client.get("/api/sets/" + frozen["set_id"]).json()
    assert "answer_spec" not in json.dumps(public)
    response = client.post(
        "/api/runs",
        json={"set_id": frozen["set_id"], "model_ids": ["mock-reference", "mock-wrong"]},
    )
    assert response.status_code == 200
    ids = response.json()["run_ids"]
    reports = [finish(client, id) for id in ids]
    assert [r["correct"] for r in reports] == [20, 0]
    event = client.get(f"/api/runs/{ids[0]}/events", headers={"Last-Event-ID": "999"})
    assert "event: progress" in event.text
    assert '"completed": 20' in event.text
    compare = client.get("/api/compare", params={"ids": ",".join(ids)}).json()
    assert compare["comparable"] is True
    assert any("Mock" in w for w in compare["warnings"])
    for format in ["jsonl", "csv", "markdown"]:
        exported = client.get(f"/api/runs/{ids[0]}/export/{format}")
        assert exported.status_code == 200
        assert "attachment" in exported.headers["content-disposition"]
    assert len(client.get("/api/runs").json()) == 2


def test_origin_host_csrf_and_body_guards(client):
    assert client.get("/api/health", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 403
    assert (
        client.post("/api/sets", data="{}", headers={"Content-Type": "text/plain"}).status_code
        == 415
    )
    assert client.get("/api/health", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert (
        client.post(
            "/api/sets", json=config(), headers={"Origin": "http://127.0.0.1:5173"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/sets",
            content='"' + "a" * 1_000_000 + '"',
            headers={"Content-Type": "application/json"},
        ).status_code
        == 413
    )


def test_unverified_and_invalid_operations(client):
    model = {"model_id": "codex", "name": "Codex", "backend": "codex-app-server"}
    registered = client.post("/api/models", json=model)
    assert registered.json()["capabilities"]["available"] is False
    frozen = client.post("/api/sets", json=config()).json()
    denied = client.post(
        "/api/runs", json={"set_id": frozen["set_id"], "model_ids": ["mock-reference", "codex"]}
    )
    assert denied.status_code == 409
    assert client.get("/api/runs").json() == []  # No partial multi-model run creation.
    assert (
        client.post("/api/sets", json={**config(), "generator_ids": ["unregistered"]}).status_code
        == 422
    )
    assert (
        client.post("/api/models", json={**model, "endpoint": "http://169.254.169.254"}).status_code
        == 422
    )
    assert client.get("/api/runs/not-real").status_code == 404
    assert client.get("/api/runs/x%27%3BDELETE%20FROM%20runs%3B--").status_code == 404
    assert client.get("/api/health").status_code == 200


def test_user_preset_persistence_and_migration(client):
    result = client.post("/api/presets", json={"name": "数学用", "config": config()})
    assert result.status_code == 200
    saved = next(p for p in client.get("/api/presets").json() if p["id"] == result.json()["id"])
    assert saved["config"]["custom"] is True
    assert saved["config"]["profile"] == "custom"
    db = client.app.state.store
    db.migrate()
    with db.connection() as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 2
    assert len(db.presets()) == 1


def test_cli_generate_run_export_and_no_overwrite(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_DATA_DIR", str(tmp_path / "cli"))
    runner = CliRunner()
    generated = runner.invoke(
        cli, ["generate", "--generators", "math.linear,data.aggregate", "--count", "4"]
    )
    assert generated.exit_code == 0, generated.output
    set_id = json.loads(generated.output)["set_id"]
    result = runner.invoke(cli, ["run", set_id])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["correct"] == 4
    output = tmp_path / "report.md"
    assert runner.invoke(cli, ["report", report["id"], "--output", str(output)]).exit_code == 0
    previous = output.read_text(encoding="utf-8")
    assert "100.0%" in previous
    assert runner.invoke(cli, ["report", report["id"], "--output", str(output)]).exit_code == 1
    assert output.read_text(encoding="utf-8") == previous


def test_csv_formula_sanitization():
    report = {
        "results": [
            {
                "problem_id": "id",
                "status": "incorrect",
                "answer": '=HYPERLINK("evil")',
                "reason": "test",
                "latency_seconds": 1,
                "problem": {"category_id": "01", "origin": "fixed", "target_difficulty": 50},
            }
        ]
    }
    csv, _ = export_report(report, "csv")
    assert "'=HYPERLINK" in csv


def test_cli_private_and_independent_sets(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_DATA_DIR", str(tmp_path / "cli"))
    runner = CliRunner()
    for args in [["speed-probe"], ["tool-set", "--mode", "agent"], ["code-set"]]:
        result = runner.invoke(cli, args)
        assert result.exit_code == 0, result.output
        assert "set-" in result.output
    model = tmp_path / "model.json"
    model.write_text(json.dumps({"model_id": "cli-model", "name": "CLI", "backend": "mock"}))
    assert runner.invoke(cli, ["model-register", str(model)]).exit_code == 0
