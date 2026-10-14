import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from llm_benchmark.api import create_app
from llm_benchmark.calibration import analyze_calibration
from llm_benchmark.cli import app
from llm_benchmark.domain import ModelConfig, Result
from llm_benchmark.runner import summarize


@pytest.fixture
def reports(store, frozen):
    # Software fixtures only; never claimed as actual model measurements.
    ids = []
    for number in range(2):
        id = store.create_run(
            frozen.set_id, ModelConfig(model_id=f"fixture-{number}", name="Fixture", backend="mock")
        )
        for i, p in enumerate(frozen.problems):
            status = "correct" if number == 0 else "timeout"
            store.save_result(
                id,
                Result(
                    index=i,
                    problem_id=p.problem_id,
                    status=status,
                    correct=number == 0,
                    answer="fixture",
                    reason="fixture",
                    latency_seconds=1,
                ),
            )
        with store.connection() as con:
            con.execute("UPDATE runs SET status='completed' WHERE id=?", (id,))
        ids.append(id)
    values = [summarize(store, id) for id in ids]
    for n, value in enumerate(values):
        value["test_only"] = False
        value["model"]["backend"] = "ollama"
        value["model"]["model"] = f"fixture-{n}"
    return values


def test_denominator_coverage_missing_bins_and_no_calibration(reports):
    result = analyze_calibration(reports)
    assert result["model_count"] == 2
    assert result["calibrated"] is False
    assert all(item["observed_accuracy"] == 0.5 for item in result["items"])
    assert all(item["empirical_difficulty"] is None for item in result["items"])
    assert sum(b["observations"] for b in result["by_difficulty"]) == 40
    assert sum(b["correct"] for b in result["by_difficulty"]) == 20
    assert all(item["status_counts"] == {"correct": 1, "timeout": 1} for item in result["items"])
    encoded = json.dumps(result)
    assert "answer_spec" not in encoded and "raw_output" not in encoded and "prompt" not in encoded


@pytest.mark.parametrize(
    "case",
    [
        "mock",
        "unfinished",
        "speed",
        "tools",
        "identity",
        "set",
        "grader",
        "missing",
        "duplicate_item",
        "order",
        "version",
        "same_model",
        "repeat_run",
        "policy",
    ],
)
def test_reject_ineligible_or_incompatible_observations(reports, case):
    r = reports[1]
    if case == "mock":
        r["test_only"] = True
    if case == "unfinished":
        r["provisional"] = True
    if case == "speed":
        r["profile_version"] = "Speed probe v1"
    if case == "tools":
        r["measurement_kind"] = "agent"
    if case == "identity":
        r["model_identity_changed"] = True
    if case == "set":
        r["set_hash"] = "different"
    if case == "grader":
        r["grader_version"] = "different"
    if case == "missing":
        r["results"].pop()
    if case == "duplicate_item":
        r["results"][0] = deepcopy(r["results"][1])
    if case == "order":
        r["results"].reverse()
    if case == "version":
        r["results"][0]["problem"]["generator_version"] = "different"
    if case == "same_model":
        r["model"] = {**reports[0]["model"], "name": "Alias", "model_id": "alias", "temperature": 1}
    if case == "repeat_run":
        r["id"] = reports[0]["id"]
    if case == "policy":
        for report in reports:
            report["model"]["backend"] = "transformers"
        reports[0]["response_text_policies"] = ["decoded-v1"]
        r["response_text_policies"] = ["qwen3-thinking-v1"]
    with pytest.raises(ValueError):
        analyze_calibration(reports)


def test_retry_counts_only_latest_and_warns(reports):
    reports[0]["attempts"].append(deepcopy(reports[0]["attempts"][0]))
    result = analyze_calibration(reports)
    assert result["items"][0]["observations"] == 2
    assert any("選択バイアス" in w for w in result["warnings"])


def test_boundary_100_and_empty_bin(reports):
    for r in reports:
        for row in r["results"]:
            row["problem"]["target_difficulty"] = 100
    bins = analyze_calibration(reports)["by_difficulty"]
    assert bins[-1]["observations"] == 40
    assert bins[0]["observed_accuracy"] is None


def test_api_and_cli_export_no_overwrite(reports, tmp_path, monkeypatch):
    by_id = {r["id"]: r for r in reports}

    def fixture_report(store, id):
        return by_id[id]

    monkeypatch.setattr("llm_benchmark.api.summarize", fixture_report)
    monkeypatch.setattr("llm_benchmark.cli.summarize", fixture_report)
    monkeypatch.setenv("FORGE_DATA_DIR", str(tmp_path / "cli-data"))
    ids = ",".join(by_id)
    with TestClient(create_app(tmp_path / "api-data"), base_url="http://127.0.0.1") as client:
        response = client.get("/api/calibration-analysis", params={"ids": ids})
        assert response.status_code == 200
        assert response.json()["model_count"] == 2
        assert client.get("/api/calibration-analysis", params={"ids": "one"}).status_code == 422
    target = tmp_path / "analysis.json"
    runner = CliRunner()
    result = runner.invoke(app, ["calibration-analysis", ids, str(target)])
    assert result.exit_code == 0, result.output
    original = target.read_bytes()
    assert json.loads(original)["calibrated"] is False
    assert runner.invoke(app, ["calibration-analysis", ids, str(target)]).exit_code == 1
    assert target.read_bytes() == original
