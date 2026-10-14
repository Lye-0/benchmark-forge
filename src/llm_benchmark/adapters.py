"""Only public prompts cross the adapter boundary. Mock is never a model score."""

import asyncio
import json
import re
import statistics
import time
from datetime import datetime, timedelta
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from llm_benchmark.domain import ModelConfig, PublicProblem, Response, canonical, digest
from llm_benchmark.ollama_wire import finish, read_json, read_stream


class AdapterError(RuntimeError):
    pass


class ExecutionUnavailable(AdapterError):
    """Infrastructure/protocol failure; do not grade or advance the problem."""


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
    if prompt.startswith("コード課題: filtered-square-sum"):
        import re

        match = re.search(r"うち(-?\d+)以上", prompt)
        if match is None:
            raise AdapterError("コード課題の形式が不正です")
        threshold = int(match[1])
        return f"def solve(values):\n    total = 0\n    for value in values:\n        if value % 2 == 0 and value >= {threshold}:\n            total += value ** 2\n    return total"
    if prompt.startswith("速度測定 "):
        import re

        match = re.search(r"xを(\d+)個", prompt)
        if match is None:
            raise AdapterError("速度試験の形式が不正です")
        count = int(match[1])
        return " ".join(["x"] * count)
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
        if "contract" not in data:
            return next(k for k, v in data["options"].items() if v == "range(1, n + 1)")
        spec = data["contract"]
        matching = []
        for label, option in data["options"].items():
            valid = True
            for a, b in data["cases"]:
                first = a + (not spec["lower_inclusive"])
                last = b - (not spec["upper_inclusive"])
                wanted = []
                x = first
                while x <= last:
                    if not any(x % m == v for m, v in spec["exclude"]):
                        wanted.append(x)
                    x += spec["step"]
                actual = [
                    x
                    for x in range(
                        a + option["start_offset"], b + option["stop_offset"], option["step"]
                    )
                    if not any(x % m == v for m, v in option["exclude"])
                ]
                valid = valid and actual == wanted
            if valid:
                matching.append(label)
        if len(matching) != 1:
            raise ValueError("修正候補が一意ではありません")
        return matching[0]
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
        if "constraints" not in data:
            answer = {"name": "inventory.lookup", "arguments": {"item_id": data["item_id"]}}
        else:
            eligible = []
            for name, definition in data["tools"].items():
                mismatches = set(data["constraints"].items()) - set(
                    definition["attributes"].items()
                )
                missing = set(definition["required"]) - set(data["available_arguments"])
                if not mismatches and not missing:
                    eligible.append(name)
            if len(eligible) != 1:
                raise ValueError("API候補が一意ではありません")
            name = eligible[0]
            answer = {
                "name": name,
                "arguments": {
                    key: data["available_arguments"][key] for key in data["tools"][name]["required"]
                },
            }
    else:
        from llm_benchmark.mock_extra import solve as solve_extra
        from llm_benchmark.mock_language import solve as solve_language
        from llm_benchmark.mock_reasoning import SUPPORTED_IDS
        from llm_benchmark.mock_reasoning import solve as solve_reasoning
        from llm_benchmark.mock_systems import solve as solve_systems

        if task in SUPPORTED_IDS:
            answer = solve_reasoning(task, data)
        elif task in {
            "language.quantifiers",
            "language.reference",
            "reading.entailment",
            "context.policy",
            "instruction.priority",
            "dialogue.correction",
            "robust.injection",
            "robust.premise",
        }:
            answer = solve_language(task, data)
        elif task in {
            "cs.round_robin",
            "cs.routing",
            "cs.permissions",
            "data.schema",
            "data.antijoin",
            "code.types",
            "code.bug_tests",
            "temporal.intersections",
        }:
            answer = solve_systems(task, data)
        else:
            answer = solve_extra(task, data)
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
                    "seed": self.config.inference_seed,
                    "num_predict": self.config.max_tokens,
                }
                if self.config.context_length is not None:
                    options["num_ctx"] = self.config.context_length
                started = time.perf_counter()
                async with client.stream(
                    "POST",
                    self.endpoint + "/api/chat",
                    json={
                        "model": self.config.model,
                        "stream": self.config.streaming,
                        "messages": [{"role": "user", "content": problem.prompt}],
                        "options": options,
                    },
                ) as response:
                    response.raise_for_status()
                    if self.config.streaming:
                        return await read_stream(response, started)
                    data = await read_json(response)
                    text = data["message"]["content"]
                    if not isinstance(text, str):
                        raise ValueError("invalid response")
                    return finish(text, data)
            except httpx.ConnectTimeout as e:
                raise ExecutionUnavailable("Ollamaへの接続がタイムアウトしました") from e
            except httpx.TimeoutException as e:
                raise TimeoutError("Ollama応答タイムアウト") from e
            except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as e:
                # Upstream response bodies and URLs can contain secrets: never expose them.
                raise ExecutionUnavailable(
                    "Ollamaから回答を取得できません。接続・モデル名・モデルのロード状態を確認してください"
                ) from e

    async def tool_turn(self, messages: list[dict], tools: list[dict]) -> dict:
        async with httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            trust_env=False,
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            try:
                options = {
                    "temperature": self.config.temperature,
                    "seed": self.config.inference_seed,
                    "num_predict": self.config.max_tokens,
                }
                if self.config.context_length is not None:
                    options["num_ctx"] = self.config.context_length
                r = await client.post(
                    self.endpoint + "/api/chat",
                    json={
                        "model": self.config.model,
                        "messages": messages,
                        "tools": tools,
                        "stream": False,
                        "options": options,
                    },
                )
                r.raise_for_status()
                message = r.json()["message"]
                if not isinstance(message, dict) or len(canonical(message)) > 64000:
                    raise ValueError("invalid message")
                # Keep protocol content only, never backend metadata or unexpected fields.
                return {key: message[key] for key in ("content", "tool_calls") if key in message}
            except httpx.ConnectTimeout as exc:
                raise ExecutionUnavailable("Ollamaへの接続がタイムアウトしました") from exc
            except httpx.TimeoutException as exc:
                raise TimeoutError("Ollamaツール応答タイムアウト") from exc
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                raise ExecutionUnavailable(
                    "Ollamaからツール応答を取得できません。接続・モデルのロード状態を確認してください"
                ) from exc

    async def check(self) -> dict:
        async with httpx.AsyncClient(
            timeout=3, trust_env=False, follow_redirects=False, transport=self.transport
        ) as client:
            try:
                async with client.stream("GET", self.endpoint + "/api/tags") as r:
                    r.raise_for_status()
                    data = await read_json(r)
                models = data["models"]
                names = [m["name"] for m in models]
                selected = next(
                    (
                        m
                        for m in models
                        if m["name"] in {self.config.model, self.config.model + ":latest"}
                    ),
                    None,
                )
                if selected is None:
                    return {
                        "status": "model_missing",
                        "reason": "指定モデルが見つかりません",
                        "models": names,
                    }
                model_digest = selected.get("digest")
                if isinstance(model_digest, str):
                    model_digest = model_digest.removeprefix("sha256:").lower()
                if not isinstance(model_digest, str) or not re.fullmatch(
                    r"[0-9a-f]{64}", model_digest
                ):
                    model_digest = None
                detected = None
                template_hash = None
                context = None
                # Older backends may lack /show capabilities: unknown is not unsupported.
                try:
                    async with client.stream(
                        "POST", self.endpoint + "/api/show", json={"model": self.config.model}
                    ) as r:
                        r.raise_for_status()
                        info = await read_json(r)
                    values = info.get("capabilities")
                    if isinstance(values, list) and all(isinstance(v, str) for v in values):
                        detected = {"tools": "tools" in values, "vision": "vision" in values}
                    if isinstance(info.get("template"), str):
                        template_hash = digest(info["template"])
                    context = next(
                        (
                            v
                            for k, v in info.get("model_info", {}).items()
                            if k.endswith(".context_length")
                            and type(v) is int
                            and 0 < v <= 10_000_000
                        ),
                        None,
                    )
                except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
                    pass
                reason = "接続確認済み。実推論は未検証。"
                reason += (
                    " モデルのツール対応情報なし。"
                    if detected is None
                    else " モデルのツール対応: "
                    + ("あり（申告情報）" if detected["tools"] else "なし")
                )
                return {
                    "status": "connected",
                    "models": names,
                    "reason": reason,
                    "detected_capabilities": detected,
                    "template_hash": template_hash,
                    "model_digest": model_digest,
                    "digest_scope": "Ollamaが報告したモデルmanifestのdigest。重みファイルを直接ハッシュした値ではありません",
                    "context_length": context,
                    "live_verified": False,
                }
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                return {"status": "unavailable", "reason": "Ollamaに接続できません"}


def capabilities(config: ModelConfig) -> dict:
    common = {
        "text": True,
        "native_tools": config.backend == "mock"
        or (config.backend == "ollama" and config.native_tools),
        "agent": config.backend == "mock" or (config.backend == "ollama" and config.native_tools),
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
