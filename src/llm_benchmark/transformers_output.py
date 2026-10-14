"""Versioned transport parsing; never consult an answer key or loosen grading."""


def separate_response(raw: str, *, model_type: str, prompt: str) -> tuple[str, dict]:
    metrics: dict = {"response_text_policy": "decoded-v1"}
    if model_type not in {"qwen3", "qwen3_moe"}:
        return raw, metrics
    metrics["response_text_policy"] = "qwen3-thinking-v1"
    # Only the leading model-specific thinking channel is transport framing.
    # A quoted tag in an ordinary answer must not remove preceding content.
    if raw.startswith("<think>"):
        body = raw[len("<think>") :]
    elif prompt.endswith("<think>\n") or prompt.endswith("<think>"):
        body = raw
    else:
        return raw, metrics
    metrics["raw_output"] = raw
    if "</think>" not in body:
        metrics["thinking_complete"] = False
        return "", metrics
    _, answer = body.split("</think>", 1)
    metrics["thinking_complete"] = True
    # Qwen's separator is two newlines. Preserve all other answer whitespace.
    if answer.startswith("\n\n"):
        answer = answer[2:]
    return answer, metrics


def termination_reason(tokens: list[int], eos_ids, max_tokens: int) -> str | None:
    if isinstance(eos_ids, int):
        eos_ids = [eos_ids]
    if isinstance(eos_ids, (list, tuple)) and tokens and tokens[-1] in eos_ids:
        return "stop"
    if len(tokens) >= max_tokens:
        return "length"
    return None
