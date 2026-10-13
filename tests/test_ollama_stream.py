import asyncio
import json

import httpx
import pytest

from llm_benchmark.adapters import AdapterError, OllamaAdapter
from llm_benchmark.domain import ModelConfig, PublicProblem


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closed = True


def adapter(stream):
    def handler(request):
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, stream=stream)

    return OllamaAdapter(
        ModelConfig(model_id="s", name="s", backend="ollama", streaming=True),
        httpx.MockTransport(handler),
    )


def wire(event):
    return (json.dumps(event, ensure_ascii=False) + "\n").encode()


async def test_incremental_utf8_ttft_and_backend_metrics(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr("llm_benchmark.ollama_wire.time.perf_counter", lambda: clock[0])

    class Timed(Stream):
        async def __aiter__(self):
            yield wire({"message": {"content": "", "thinking": "not an answer"}, "done": False})
            clock[0] = 10.5
            data = wire({"message": {"content": "日本"}, "done": False})
            # Arbitrary network boundaries may split UTF-8 codepoints and lines.
            yield data[:26]
            yield data[26:]
            clock[0] = 12.0
            yield wire(
                {
                    "message": {"content": "語"},
                    "done": True,
                    "eval_count": 3,
                    "eval_duration": 1_000_000_000,
                    "prompt_eval_count": 10,
                    "load_duration": 0,
                }
            )

    stream = Timed([])
    response = await adapter(stream).complete(PublicProblem(problem_id="p", prompt="public"))
    assert response.text == "日本語"
    assert response.ttft_seconds == 0.5
    assert response.decode_seconds == 1
    assert response.metrics["input_tokens"] == 10
    assert response.metrics["load_duration_seconds"] == 0
    assert stream.closed


@pytest.mark.parametrize(
    "chunks",
    [
        [wire({"message": {"content": "partial"}, "done": False})],
        [wire({"error": "secret-upstream"})],
        [b"not JSON\n"],
        [wire({"done": True, "eval_count": -1})],
        [wire({"done": True, "eval_duration": True})],
        [wire({"done": True}), wire({"done": True})],
        [b"x" * 2_000_001],
    ],
)
async def test_stream_failures_are_bounded_sanitized_and_closed(chunks):
    stream = Stream(chunks)
    with pytest.raises(AdapterError) as error:
        await adapter(stream).complete(PublicProblem(problem_id="p", prompt="public"))
    assert "secret-upstream" not in str(error.value)
    assert stream.closed


async def test_cancel_closes_inflight_stream():
    entered = asyncio.Event()

    class Blocking(Stream):
        async def __aiter__(self):
            entered.set()
            yield wire({"message": {"content": "partial"}, "done": False})
            await asyncio.sleep(60)

    stream = Blocking([])
    task = asyncio.create_task(
        adapter(stream).complete(PublicProblem(problem_id="p", prompt="public"))
    )
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.closed


@pytest.mark.parametrize(
    "show",
    [
        {
            "capabilities": ["completion", "tools"],
            "template": "private template",
            "model_info": {"llama.context_length": 4096},
        },
        {},
    ],
)
async def test_model_capabilities_are_unknown_or_reported_never_live_verified(show):
    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "local:latest"}]})
        return httpx.Response(200, json=show)

    config = ModelConfig(model_id="m", name="m", backend="ollama", model="local")
    result = await OllamaAdapter(config, httpx.MockTransport(handler)).check()
    assert result["status"] == "connected" and result["live_verified"] is False
    assert "private template" not in json.dumps(result)
    if show:
        assert result["detected_capabilities"]["tools"] is True
        assert result["context_length"] == 4096
        assert len(result["template_hash"]) == 64
    else:
        assert result["detected_capabilities"] is None


@pytest.mark.parametrize(
    "value,expected",
    [("a" * 64, "a" * 64), ("sha256:" + "B" * 64, "b" * 64), ("bad", None), (None, None)],
)
async def test_model_manifest_digest_is_validated(value, expected):
    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "local:latest", "digest": value}]})
        return httpx.Response(200, json={})

    result = await OllamaAdapter(
        ModelConfig(model_id="m", name="m", backend="ollama", model="local"),
        httpx.MockTransport(handler),
    ).check()
    assert result["model_digest"] == expected
    assert "manifest" in result["digest_scope"]


@pytest.mark.parametrize("streaming", [False, True])
async def test_explicit_inference_seed_reaches_text_and_tool_requests(streaming):
    seen = []

    def handler(request):
        payload = json.loads(request.content)
        seen.append(payload["options"]["seed"])
        value = {"message": {"content": "fixture"}, "done": True}
        return (
            httpx.Response(200, content=wire(value))
            if payload["stream"]
            else httpx.Response(200, json=value)
        )

    config = ModelConfig(
        model_id="seeded",
        name="seeded",
        backend="ollama",
        streaming=streaming,
        inference_seed=12345,
    )
    adapter = OllamaAdapter(config, httpx.MockTransport(handler))
    await adapter.complete(PublicProblem(problem_id="p", prompt="public"))
    await adapter.tool_turn([], [])
    assert seen == [12345, 12345]
