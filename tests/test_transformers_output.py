from copy import deepcopy

import pytest

from llm_benchmark.domain import AnswerSpec, Result
from llm_benchmark.grading import grade
from llm_benchmark.runner import comparison
from llm_benchmark.transformers_output import separate_response, termination_reason


def test_qwen_thinking_is_transport_not_a_relaxed_grader():
    raw = "<think>fixture reasoning</think>\n\n12"
    text, metrics = separate_response(raw, model_type="qwen3", prompt="public")
    spec = AnswerSpec(type="number", expected=12)
    assert not grade(raw, spec).correct
    assert grade(text, spec).correct
    assert metrics["raw_output"] == raw
    assert metrics["thinking_complete"] is True
    assert metrics["response_text_policy"] == "qwen3-thinking-v1"
    wrong, _ = separate_response(raw, model_type="qwen3", prompt="public")
    assert not grade(wrong, AnswerSpec(type="number", expected=13)).correct


@pytest.mark.parametrize("model_type", ["qwen3", "qwen3_moe"])
def test_prompt_prefilled_thinking_and_unfinished_channel(model_type):
    answer, metrics = separate_response(
        "fixture</think>\n\n  final \n", model_type=model_type, prompt="user\n<think>\n"
    )
    assert answer == "  final \n"
    assert metrics["thinking_complete"] is True
    answer, metrics = separate_response("<think>12", model_type=model_type, prompt="user")
    assert answer == ""
    assert metrics["thinking_complete"] is False


@pytest.mark.parametrize(
    ("model_type", "raw"),
    [
        ("other", "<think>literal</think>\n\n12"),
        ("qwen3", "quote: <think>x</think>"),
        ("qwen3", "12"),
        ("qwen3", "unmatched </think>12"),
    ],
)
def test_unrecognized_or_nonleading_tags_preserve_entire_answer(model_type, raw):
    answer, metrics = separate_response(raw, model_type=model_type, prompt="user")
    assert answer == raw
    assert "raw_output" not in metrics


@pytest.mark.parametrize(
    ("tokens", "eos", "limit", "expected"),
    [
        ([1, 2], 2, 2, "stop"),
        ([1, 2], [2, 3], 5, "stop"),
        ([1, 2], 3, 2, "length"),
        ([1], None, 2, None),
        ([], 2, 2, None),
    ],
)
def test_eos_takes_precedence_over_length(tokens, eos, limit, expected):
    assert termination_reason(tokens, eos, limit) == expected


def test_legacy_and_separated_runs_are_not_directly_comparable():
    old = {
        "set_hash": "same",
        "grader_version": "same",
        "test_only": False,
        "provisional": False,
        "environment": {},
        "model": {
            "backend": "transformers",
            "temperature": 0,
            "max_tokens": 10,
            "timeout_seconds": 30,
        },
    }
    new = deepcopy(old)
    new["response_text_policies"] = ["qwen3-thinking-v1"]
    assert not comparison([old, new])["comparable"]
    assert comparison([new, new])["comparable"]


def test_summary_omits_raw_output_but_full_result_retains_it(store, frozen):
    run_id = store.create_run(frozen.set_id, store.get_model("mock-reference"))
    store.save_result(
        run_id,
        Result(
            index=0,
            problem_id=frozen.problems[0].problem_id,
            status="incorrect",
            correct=False,
            answer="12",
            reason="fixture",
            latency_seconds=1,
            metrics={
                "raw_output": "<think>fixture</think>\n\n12",
                "response_text_policy": "qwen3-thinking-v1",
            },
        ),
    )
    assert store.run(run_id)["results"][0].metrics["raw_output"].startswith("<think>")
    metrics = store.run(run_id, include_payloads=False)["results"][0].metrics
    assert "raw_output" not in metrics
    assert metrics["response_text_policy"] == "qwen3-thinking-v1"
