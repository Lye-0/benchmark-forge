"""Only public prompts cross the adapter boundary. Mock is never a model score."""

import asyncio
import json
import statistics
from datetime import datetime, timedelta
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from llm_benchmark.domain import ModelConfig, PublicProblem, Response, canonical


class AdapterError(RuntimeError):
    pass


def validate_endpoint(endpoint: str) -> str:
    url = urlsplit(endpoint)
    # Literal loopback only: no DNS resolution, credentials, redirect or arbitrary egress.
    if (
        url.scheme != "http"
        or url.hostname not in {"127.0.0.1", "::1"}
        or url.username
        or url.password
        or url.path not in ("", "/")
        or url.query
        or url.fragment
    ):
        raise ValueError("Ollamaの接続先は認証情報を含まないローカルHTTPアドレスに限定します")
    try:
        _ = url.port
    except ValueError as e:
        raise ValueError("ポートが不正です") from e
    return endpoint.rstrip("/")


class Adapter(Protocol):
    async def complete(self, problem: PublicProblem) -> Response: ...


def mock_solve(prompt: str) -> str:
    """Independent rule solver for software tests, not an LLM or an oracle."""
    task = prompt.splitlines()[0].removeprefix("課題: ")
    data = json.loads(prompt.split("入力(JSON):\n", 1)[1].splitlines()[0])
    if task == "math.expression":
        answer = sum(pair[0] * pair[1] for pair in data["pairs"])
    elif task == "math.linear":
        answer = (data["c"] - data["b"]) // data["a"]
    elif task == "math.median":
        answer = statistics.median(data["values"])
    elif task == "logic.order":
        links = dict(data["before"])
        incoming = {v for v in links.values()}
        item = next(v for v in links if v not in incoming)
        answer = [item]
        while item in links:
            item = links[item]
            answer.append(item)
    elif task == "logic.boolean":
        answer = [data["first"]]
        for xor in data["xor"]:
            answer.append(answer[-1] != xor)
    elif task == "algorithm.path":
        distances = [float("inf")] * data["nodes"]
        distances[0] = 0
        # Bellman-Ford, independent of generator's Dijkstra reference.
        for _ in range(data["nodes"] - 1):
            for a, b, weight in data["edges"]:
                distances[b] = min(distances[b], distances[a] + weight)
        answer = distances[-1]
    elif task == "code.trace":
        answer = 0
        for v in data["values"]:
            if v % data["modulus"]:
                answer += v - 1
            else:
                answer += v * 2
    elif task == "code.debug":
        return next(k for k, v in data["options"].items() if v == "range(1, n + 1)")
    elif task == "data.aggregate":
        answer = dict.fromkeys(["alpha", "beta", "gamma"], 0)
        for row in data["rows"]:
            if row["value"] >= data["threshold"]:
                answer[row["group"]] += row["value"]
    elif task == "data.join":
        answer = {p["id"]: 0 for p in data["products"]}
        prices = {p["id"]: p["price"] for p in data["products"]}
        for row in data["orders"]:
            answer[row["id"]] += prices[row["id"]] * row["quantity"]
    elif task == "instruction.format":
        return "|".join(str(v) for v in sorted(data["values"]) if v % 2 == 0 and v >= 0)
    elif task == "temporal.offset":
        date = datetime.strptime(data["start_utc"], "%Y-%m-%d %H:%M")
        for offset in data["offsets_minutes"]:
            date += timedelta(minutes=offset)
        return date.strftime("%Y-%m-%d %H:%M")
    elif task == "dialogue.state":
        answer = {}
        for event in data["events"]:
            answer[event["field"]] = event["value"]
    elif task == "tool.select":
        answer = {"name": "inventory.lookup", "arguments": {"item_id": data["item_id"]}}
    else:
        raise AdapterError("Mockソルバーの未対応課題です")
    return canonical(answer)


class MockAdapter:
    def __init__(self, config: ModelConfig):
        self.config = config

    async def complete(self, problem: PublicProblem) -> Response:
        await asyncio.sleep(0.025)
        match self.config.mock_behavior:
            case "timeout":
                await asyncio.sleep(self.config.timeout_seconds + 1)
                raise TimeoutError
            case "error":
                raise AdapterError("意図的なMockエラー")
            case "wrong":
                return Response(text="MOCK_WRONG")
            case "empty":
                return Response(text="")
        return Response(text=mock_solve(problem.prompt))


class OllamaAdapter:
    def __init__(self, config: ModelConfig, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self.endpoint = validate_endpoint(config.endpoint)
        self.transport = transport

    async def complete(self, problem: PublicProblem) -> Response:
        async with httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            trust_env=False,
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            try:
                options: dict[str, float | int] = {
                    "temperature": self.config.temperature,
                    "seed": 0,
                    "num_predict": self.config.max_tokens,
                }
                if self.config.context_length is not None:
                    options["num_ctx"] = self.config.context_length
                response = await client.post(
                    self.endpoint + "/api/chat",
                    json={
                        "model": self.config.model,
                        "stream": False,
                        "messages": [{"role": "user", "content": problem.prompt}],
                        "options": options,
                    },
                )
                response.raise_for_status()
                data = response.json()
                text = data["message"]["content"]
                if not isinstance(text, str) or len(text) > 200_000:
                    raise ValueError("invalid response")
                tokens = data.get("eval_count")
                duration = data.get("eval_duration")
                return Response(
                    text=text,
                    output_tokens=tokens,
                    decode_seconds=duration / 1e9 if duration and duration > 0 else None,
                )
            except httpx.TimeoutException as e:
                raise TimeoutError("Ollama応答タイムアウト") from e
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
                # Upstream response bodies and URLs can contain secrets: never expose them.
                raise AdapterError(
                    "Ollama通信・応答エラー。ローカルサービスとモデル名を確認してください"
                ) from e

    async def check(self) -> dict:
        async with httpx.AsyncClient(
            timeout=3, trust_env=False, transport=self.transport
        ) as client:
            try:
                r = await client.get(self.endpoint + "/api/tags")
                r.raise_for_status()
                names = [m["name"] for m in r.json()["models"]]
                found = self.config.model in names or self.config.model + ":latest" in names
                return {
                    "status": "connected" if found else "model_missing",
                    "models": names,
                    "reason": "接続確認済み。実推論はローカルで別途検証してください"
                    if found
                    else "指定モデルが見つかりません",
                }
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                return {"status": "unavailable", "reason": "Ollamaに接続できません"}


def capabilities(config: ModelConfig) -> dict:
    common = {
        "text": True,
        "native_tools": False,
        "agent": False,
        "images": False,
        "live_verified": False,
        "quantization": config.quantization,
        "execution_path": config.backend,
        "test_only": config.backend == "mock",
    }
    if config.backend == "mock":
        return {
            **common,
            "available": True,
            "status": "test-only",
            "reason": "ソフトウェア検証専用。モデル性能・ランキングには使用できません",
        }
    if config.backend == "ollama":
        return {
            **common,
            "available": True,
            "status": "NOT_VERIFIED",
            "reason": "ローカル接続対応。実モデル推論は未検証",
        }
    if config.backend == "transformers":
        from llm_benchmark.transformers_adapter import readiness

        reason = readiness(config)
        return {
            **common,
            "available": reason is None,
            "status": "unavailable" if reason else "NOT_VERIFIED",
            "reason": reason
            or "別プロセス・ローカルモデル専用。実推論は未検証。問題ごとにロードします",
        }
    return {
        **common,
        "available": False,
        "status": "NOT_VERIFIED",
        "execution_path": "codex-agent",
        "reason": "公式イベント契約をMock試験。ツール禁止とファイル隔離が未検証のため実接続は無効",
    }


def make_adapter(config: ModelConfig) -> Adapter:
    if config.backend == "mock":
        return MockAdapter(config)
    if config.backend == "ollama":
        return OllamaAdapter(config)
    if config.backend == "transformers":
        from llm_benchmark.transformers_adapter import TransformersAdapter, readiness

        reason = readiness(config)
        if reason:
            raise AdapterError(reason)
        return TransformersAdapter(config)
    raise AdapterError(capabilities(config)["reason"])
