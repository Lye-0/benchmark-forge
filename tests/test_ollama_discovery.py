import httpx
import pytest

from llm_benchmark.adapters import AdapterError
from llm_benchmark.ollama_discovery import installed_models


@pytest.mark.asyncio
async def test_discovery_reads_tags_only_and_sanitizes_optional_metadata():
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/api/tags"
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "qwen:small",
                        "digest": "sha256:" + "a" * 64,
                        "details": {"quantization_level": "Q4_K_M"},
                        "size": 1234,
                    },
                    {"name": "gemma:test", "digest": "invalid", "size": True},
                ]
            },
        )

    values = await installed_models(
        "http://127.0.0.1:11434", transport=httpx.MockTransport(handler)
    )
    assert values[0] == {
        "name": "gemma:test",
        "revision": None,
        "quantization": None,
        "size_bytes": None,
    }
    assert values[1]["revision"] == "a" * 64
    assert values[1]["quantization"] == "Q4_K_M"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.com",
        "http://localhost:11434",
        "https://127.0.0.1",
        "http://user:pass@127.0.0.1",
    ],
)
async def test_discovery_rejects_non_literal_local_endpoint(endpoint):
    def handler(request):
        pytest.fail("must reject before network")

    with pytest.raises((ValueError, AdapterError)):
        await installed_models(endpoint, transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,payload",
    [(302, {}), (200, {"models": "bad"}), (200, {"models": [{"name": "a" * 201}]}), (500, {})],
)
async def test_discovery_rejects_bad_or_redirect_response(status, payload):
    def handler(request):
        return httpx.Response(status, json=payload, headers={"Location": "http://example.com"})

    with pytest.raises(AdapterError, match="モデル一覧を取得できません"):
        await installed_models("http://127.0.0.1:11434", transport=httpx.MockTransport(handler))
