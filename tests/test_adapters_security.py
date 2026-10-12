import asyncio
import json
from collections import deque

import httpx
import pytest

from llm_benchmark.adapters import (
    AdapterError,
    OllamaAdapter,
    capabilities,
    make_adapter,
    validate_endpoint,
)
from llm_benchmark.codex_protocol import AppServerSession, parse_cli_events
from llm_benchmark.domain import ModelConfig, PublicProblem
from llm_benchmark.generators import REGISTRY
from llm_benchmark.sandbox import IsolationUnavailable, execute_code, sandbox_status


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://example.com",
        "http://localhost:11434",
        "http://127.0.0.1.example.com",
        "http://2130706433",
        "file:///etc/passwd",
        "http://user:password@127.0.0.1:11434",
        "http://127.0.0.1/api",
        "http://169.254.169.254",
        "http://[::1]:notaport",
        "http://127.0.0.1?next=external",
    ],
)
def test_ssrf_and_credentials_rejected(endpoint):
    with pytest.raises(ValueError):
        validate_endpoint(endpoint)


async def test_ollama_public_input_contract_and_metrics():
    problem = REGISTRY["math.linear"].generate(10, 20)

    def handler(request):
        data = json.loads(request.content)
        assert data["messages"] == [{"role": "user", "content": problem.prompt}]
        assert "answer_spec" not in request.content.decode()
        assert data["stream"] is False
        assert data["options"]["num_ctx"] == 4096
        return httpx.Response(
            200,
            json={
                "message": {"content": str(problem.answer_spec.expected)},
                "eval_count": 5,
                "eval_duration": 2_000_000_000,
            },
        )

    response = await OllamaAdapter(
        ModelConfig(model_id="ollama", name="test", backend="ollama", context_length=4096),
        httpx.MockTransport(handler),
    ).complete(problem.public())
    assert response.output_tokens == 5
    assert response.decode_seconds == 2
    assert response.ttft_seconds is None


async def test_ollama_failures_hide_upstream_secrets_and_redirects():
    for code in [302, 401, 429, 500]:
        transport = httpx.MockTransport(
            lambda r, code=code: httpx.Response(
                code, text="dummy-secret", headers={"Location": "http://example.com"}
            )
        )
        adapter = OllamaAdapter(
            ModelConfig(model_id="ollama", name="test", backend="ollama"), transport
        )
        with pytest.raises(AdapterError) as exc:
            await adapter.complete(PublicProblem(problem_id="test", prompt="test"))
        assert "dummy-secret" not in str(exc.value)


@pytest.mark.parametrize("backend", ["codex-cli", "codex-app-server", "transformers"])
def test_unverified_adapters_fail_closed(backend):
    config = ModelConfig(model_id="test", name="test", backend=backend)
    assert not capabilities(config)["available"]
    with pytest.raises(AdapterError):
        make_adapter(config)


def test_code_execution_never_reaches_host(tmp_path):
    marker = tmp_path / "malicious-write"
    with pytest.raises(IsolationUnavailable):
        execute_code(f"open({str(marker)!r}, 'w').write('unsafe')")
    assert not marker.exists()
    assert sandbox_status()["code_execution"] is False
    assert sandbox_status()["native_tools"] is False


def test_codex_cli_event_contract():
    lines = [
        json.dumps({"type": "thread.started", "thread_id": "thread"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "42"}}),
        json.dumps({"type": "turn.completed", "usage": {"output_tokens": 5}}),
    ]
    response = parse_cli_events(lines, 0)
    assert response.text == "42"
    assert response.output_tokens is None  # CLI accounting isn't a verified decode measure.
    for failure in [
        lines[:-1],
        ["not-json"],
        [json.dumps({"type": "turn.failed", "error": {"message": "dummy-secret"}})],
        [json.dumps({"type": "item.completed", "item": {"type": "command_execution"}})],
    ]:
        with pytest.raises(AdapterError) as exc:
            parse_cli_events(failure, 0)
        assert "dummy-secret" not in str(exc.value)
    with pytest.raises(AdapterError):
        parse_cli_events(lines, 1)


class Transport:
    def __init__(self, messages):
        self.messages = deque(messages)
        self.sent = []

    async def send(self, message):
        self.sent.append(message)

    async def receive(self):
        if not self.messages:
            await asyncio.sleep(2)
            raise TimeoutError
        return self.messages.popleft()


def rpc_start(account=True):
    return [
        {"id": 1, "result": {"userAgent": "mock"}},
        {"id": 2, "result": {"account": {"type": "chatgpt"} if account else None}},
        {"id": 3, "result": {"thread": {"id": "thread-test"}}},
        {"id": 4, "result": {"turn": {"id": "turn-test"}}},
    ]


def notification(method, **params):
    event = {
        "method": method,
        "params": {"threadId": "thread-test", "turnId": "turn-test", **params},
    }
    if method == "turn/completed":
        event["params"].pop("turnId")
        event["params"]["turn"].setdefault("id", "turn-test")
    return event


async def test_app_server_initialization_text_completion_and_scoping():
    transport = Transport(
        rpc_start()
        + [
            {
                "method": "item/completed",
                "params": {
                    "threadId": "other-thread",
                    "turnId": "turn-test",
                    "item": {"type": "agentMessage", "text": "ignore"},
                },
            },
            notification("item/completed", item={"type": "agentMessage", "text": "42"}),
            notification("turn/completed", turn={"id": "turn-test", "status": "completed"}),
        ]
    )
    result = await AppServerSession(transport).complete(
        PublicProblem(problem_id="test", prompt="public prompt")
    )
    assert result.text == "42"
    methods = [m.get("method") for m in transport.sent]
    assert methods == ["initialize", "initialized", "account/read", "thread/start", "turn/start"]
    assert transport.sent[3]["params"]["approvalPolicy"] == "never"
    assert transport.sent[4]["params"]["input"] == [{"type": "text", "text": "public prompt"}]


async def test_app_server_unauthenticated_never_starts_thread():
    transport = Transport(rpc_start(False))
    with pytest.raises(AdapterError, match="未認証"):
        await AppServerSession(transport).complete(PublicProblem(problem_id="test", prompt="test"))
    assert not any(m.get("method") == "thread/start" for m in transport.sent)


@pytest.mark.parametrize(
    "event",
    [
        notification("error", error={"message": "dummy-secret"}),
        notification("turn/completed", turn={"status": "failed"}),
        notification("item/completed", item={"type": "commandExecution"}),
        {"id": 300, "method": "item/commandExecution/requestApproval", "params": {}},
    ],
)
async def test_app_server_failure_interrupt_and_no_secret_leak(event):
    transport = Transport(rpc_start() + [event])
    with pytest.raises(AdapterError) as exc:
        await AppServerSession(transport).complete(PublicProblem(problem_id="test", prompt="test"))
    assert "dummy-secret" not in str(exc.value)
    assert transport.sent[-1]["method"] == "turn/interrupt"


async def test_app_server_timeout_and_cancellation():
    transport = Transport(rpc_start())
    with pytest.raises(TimeoutError):
        await AppServerSession(transport).complete(
            PublicProblem(problem_id="test", prompt="test"), timeout=0.05
        )
    assert transport.sent[-1]["method"] == "turn/interrupt"
    transport = Transport(rpc_start())
    task = asyncio.create_task(
        AppServerSession(transport).complete(PublicProblem(problem_id="test", prompt="test"))
    )
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert transport.sent[-1]["method"] == "turn/interrupt"
