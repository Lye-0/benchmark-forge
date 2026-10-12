"""Bounded parsing and truthful timing for Ollama's official /api/chat protocol."""

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from llm_benchmark.domain import Response


async def bounded_bytes(response: httpx.Response, limit: int = 2_000_000) -> AsyncIterator[bytes]:
    count = 0
    async for chunk in response.aiter_bytes():
        count += len(chunk)
        if count > limit:
            raise ValueError("response limit")
        yield chunk


async def read_json(response: httpx.Response, limit: int = 2_000_000) -> dict:
    body = bytearray()
    async for chunk in bounded_bytes(response, limit):
        body.extend(chunk)
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError("expected object")
    return value


def integer(data: dict, key: str) -> int | None:
    value = data.get(key)
    if value is not None and (type(value) is not int or not 0 <= value <= 10**18):
        raise ValueError("invalid backend metric")
    return value


def finish(text: str, data: dict, ttft: float | None = None) -> Response:
    if len(text) > 200_000 or "error" in data:
        raise ValueError("invalid response")
    duration = integer(data, "eval_duration")
    metrics: dict[str, Any] = {
        "timing_source": "Ollama reported durations; TTFT is client first visible content chunk"
    }
    for name in ("load_duration", "prompt_eval_duration", "total_duration"):
        value = integer(data, name)
        metrics[name + "_seconds"] = value / 1e9 if value is not None else None
    metrics["input_tokens"] = integer(data, "prompt_eval_count")
    metrics["done_reason"] = (
        data.get("done_reason") if data.get("done_reason") in {"stop", "length"} else None
    )
    return Response(
        text=text,
        output_tokens=integer(data, "eval_count"),
        decode_seconds=duration / 1e9 if duration else None,
        ttft_seconds=ttft,
        metrics=metrics,
    )


async def read_stream(response: httpx.Response, started: float) -> Response:
    pending = bytearray()
    parts: list[str] = []
    length = 0
    first_content = None
    terminal = None

    def consume(raw):
        nonlocal length, first_content, terminal
        if not raw.strip():
            return
        if terminal is not None:
            raise ValueError("event after completion")
        event = json.loads(raw)
        if not isinstance(event, dict) or "error" in event:
            raise ValueError("upstream error")
        message = event.get("message", {})
        text = message.get("content", "")
        if not isinstance(text, str):
            raise ValueError("invalid content")
        if text:
            if first_content is None:
                first_content = time.perf_counter() - started
            parts.append(text)
            length += len(text)
            if length > 200_000:
                raise ValueError("output limit")
        if event.get("done") is True:
            terminal = event

    async for chunk in bounded_bytes(response):
        pending.extend(chunk)
        while b"\n" in pending:
            line, _, rest = pending.partition(b"\n")
            pending = bytearray(rest)
            consume(line)
    if pending:
        consume(pending)
    if terminal is None:
        raise ValueError("stream ended without done")
    return finish("".join(parts), terminal, first_content)
