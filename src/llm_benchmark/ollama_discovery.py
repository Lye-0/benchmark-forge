"""Read installed Ollama model metadata without loading or downloading weights."""

import re

import httpx

from llm_benchmark.adapters import AdapterError, validate_endpoint
from llm_benchmark.ollama_wire import read_json


async def installed_models(endpoint: str, *, transport=None) -> list[dict]:
    endpoint = validate_endpoint(endpoint)
    try:
        async with httpx.AsyncClient(
            timeout=3, trust_env=False, follow_redirects=False, transport=transport
        ) as client:
            async with client.stream("GET", endpoint + "/api/tags") as response:
                response.raise_for_status()
                data = await read_json(response)
        values = data.get("models")
        if not isinstance(values, list) or len(values) > 1000:
            raise ValueError("invalid models")
        result = {}
        for item in values:
            if not isinstance(item, dict):
                raise ValueError("invalid model")
            name = item.get("name")
            if not isinstance(name, str) or not 0 < len(name) <= 200:
                raise ValueError("invalid name")
            details = item.get("details") or {}
            if not isinstance(details, dict):
                raise ValueError("invalid details")
            revision = item.get("digest")
            revision = revision.removeprefix("sha256:").lower() if isinstance(revision, str) else ""
            quantization = details.get("quantization_level")
            size = item.get("size")
            result[name] = {
                "name": name,
                "revision": revision if re.fullmatch(r"[0-9a-f]{64}", revision) else None,
                "quantization": quantization
                if isinstance(quantization, str) and 0 < len(quantization) <= 80
                else None,
                "size_bytes": size if type(size) is int and size >= 0 else None,
            }
        return [result[name] for name in sorted(result)]
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise AdapterError(
            "Ollamaのモデル一覧を取得できません。Ollamaの起動と接続先を確認してください。手入力でも登録できます。"
        ) from exc
