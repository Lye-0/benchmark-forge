from types import SimpleNamespace

import pytest

from llm_benchmark.analysis import response_evidence


@pytest.mark.parametrize("status", ["correct", "incorrect", "empty"])
def test_legacy_text_responses_are_evidence_even_when_not_correct(status):
    result = response_evidence(
        [SimpleNamespace(status=status, metrics={})], backend="ollama", mode="text"
    )
    assert result["status"] == "response_observed"
    assert result["response_results"] == 1


def test_gpu_sample_or_backend_registration_is_not_response_evidence():
    results = [SimpleNamespace(status="timeout", metrics={"gpu_sampling": {"samples": 100}})]
    assert response_evidence(results, backend="ollama", mode="text")["status"] == "not_observed"
    assert response_evidence([], backend="ollama", mode="text")["status"] == "not_observed"


def test_code_execution_error_can_follow_received_response_but_mock_stays_diagnostic():
    results = [SimpleNamespace(status="error", metrics={"backend_response_received": True})]
    assert response_evidence(results, backend="ollama", mode="code")["response_results"] == 1
    assert (
        response_evidence(results, backend="mock", mode="code")["status"] == "software_diagnostic"
    )
    assert (
        response_evidence(
            [SimpleNamespace(status="error", metrics={})], backend="ollama", mode="code"
        )["response_results"]
        == 0
    )
