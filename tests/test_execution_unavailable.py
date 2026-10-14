import httpx
import pytest
from fastapi.testclient import TestClient

from llm_benchmark.adapters import ExecutionUnavailable, OllamaAdapter, make_adapter, mock_solve
from llm_benchmark.api import create_app
from llm_benchmark.domain import ModelConfig, PublicProblem
from llm_benchmark.runner import Scheduler, summarize
from llm_benchmark.storage import Store


def setup_ollama(store, monkeypatch, handler):
    config = ModelConfig(
        model_id="offline-test", name="Offline test", backend="ollama", model="fixture"
    )
    store.save_model(config)
    monkeypatch.setattr(
        "llm_benchmark.runner.make_adapter",
        lambda config: (
            OllamaAdapter(config, httpx.MockTransport(handler))
            if config.backend == "ollama"
            else make_adapter(config)
        ),
    )
    return config


def metadata(request):
    if request.url.path == "/api/tags":
        return httpx.Response(200, json={"models": [{"name": "fixture:latest"}]})
    return httpx.Response(200, json={})


@pytest.mark.parametrize("failure", ["offline", "missing"])
async def test_preflight_creates_no_jobs_when_any_model_is_unavailable(
    store, frozen, monkeypatch, failure
):
    def handler(request):
        if failure == "offline":
            raise httpx.ConnectError("secret upstream detail")
        return httpx.Response(200, json={"models": []})

    config = setup_ollama(store, monkeypatch, handler)
    scheduler = Scheduler(store)
    with pytest.raises(ExecutionUnavailable) as exc:
        await scheduler.create_checked(frozen.set_id, ["mock-reference", config.model_id])
    assert "secret" not in str(exc.value)
    assert store.run_ids() == []
    assert scheduler.queue.empty()


async def test_disconnect_pauses_without_scoring_and_resume_retries_same_problem(
    store, frozen, monkeypatch
):
    chats = []
    offline = False

    def handler(request):
        if request.url.path != "/api/chat":
            if offline:
                raise httpx.ConnectError("secret")
            return metadata(request)
        import json

        prompt = json.loads(request.content)["messages"][0]["content"]
        chats.append(prompt)
        if len(chats) == 2:
            raise httpx.ConnectError("secret")
        return httpx.Response(200, json={"message": {"content": mock_solve(prompt)}, "done": True})

    config = setup_ollama(store, monkeypatch, handler)
    scheduler = Scheduler(store)
    scheduler.start()
    try:
        first, other = await scheduler.create_checked(
            frozen.set_id, [config.model_id, "mock-reference"]
        )
        await scheduler.queue.join()
        report = summarize(store, first)
        assert report["status"] == "paused"
        assert report["completed"] == 1
        assert report["status_counts"] == {"correct": 1}
        assert report["execution_block"]["reason"]
        assert store.run_status(other) == "completed"
        attempts = store.attempts(first)
        assert [a["status"] for a in attempts] == ["correct", "execution_unavailable"]
        assert attempts[-1]["data"]["reason"] == report["execution_block"]["reason"]
        assert "secret" not in str(attempts)
        assert Store(store.path.parent).execution_blocks()[0]["id"] == first
        await scheduler.close()
        scheduler = Scheduler(store)
        scheduler.start()
        assert store.execution_blocks()[0]["id"] == first
        offline = True
        with pytest.raises(ExecutionUnavailable):
            await scheduler.control_checked(first, "resume")
        assert store.run_status(first) == "paused"
        assert len(chats) == 2
        offline = False
        await scheduler.control_checked(first, "resume")
        await scheduler.queue.join()
        report = summarize(store, first)
        assert report["status"] == "completed"
        assert report["completed"] == report["correct"] == 20
        assert chats[1] == chats[2]
        assert len(chats) == 21
        assert report["execution_block"] is None
        assert store.execution_blocks() == []
        assert len(store.attempts(first)) == 21
    finally:
        await scheduler.close()


async def test_service_disappearing_while_queued_stops_before_first_attempt(
    store, frozen, monkeypatch
):
    config = setup_ollama(store, monkeypatch, lambda request: httpx.Response(503))
    scheduler = Scheduler(store)
    id = scheduler.create(frozen.set_id, [config.model_id])[0]
    await scheduler.execute(id)
    assert store.run_status(id) == "paused"
    assert summarize(store, id)["completed"] == 0
    assert store.attempts(id) == []
    assert store.execution_blocks()[0]["reason"] == "Ollamaに接続できません"


@pytest.mark.parametrize("kind", ["connect_timeout", "read_timeout", "http_error", "stream_error"])
@pytest.mark.parametrize("tools", [False, True])
async def test_ollama_distinguishes_execution_failure_from_answer_timeout(kind, tools):
    def handler(request):
        if kind == "connect_timeout":
            raise httpx.ConnectTimeout("secret")
        if kind == "read_timeout":
            raise httpx.ReadTimeout("secret")
        if kind == "http_error":
            return httpx.Response(500, text="secret OOM")
        return httpx.Response(200, content=b'{"error":"secret OOM"}\n')

    adapter = OllamaAdapter(
        ModelConfig(model_id="test", name="Test", backend="ollama", streaming=True),
        httpx.MockTransport(handler),
    )
    with pytest.raises(TimeoutError if kind == "read_timeout" else ExecutionUnavailable) as exc:
        if tools:
            await adapter.tool_turn([], [])
        else:
            await adapter.complete(PublicProblem(problem_id="test", prompt="test"))
    assert "secret" not in str(exc.value)


async def test_answer_timeout_remains_a_scored_timeout(store, frozen, monkeypatch):
    def handler(request):
        if request.url.path == "/api/chat":
            raise httpx.ReadTimeout("slow answer")
        return metadata(request)

    config = setup_ollama(store, monkeypatch, handler)
    scheduler = Scheduler(store)
    id = scheduler.create(frozen.set_id, [config.model_id])[0]
    await scheduler.execute(id)
    report = summarize(store, id)
    assert report["status"] == "completed"
    assert report["status_counts"] == {"timeout": 20}
    assert store.execution_blocks() == []


def test_cancel_wins_over_late_connection_failure(store, frozen):
    id = store.create_run(frozen.set_id, store.get_model("mock-reference"))
    store.status(id, "running")
    attempt = store.begin_attempt(id, 0)
    store.status(id, "cancelled")
    store.pause_unavailable(id, "offline", attempt)
    assert store.run_status(id) == "cancelled"
    assert store.execution_blocks() == []
    assert store.attempts(id)[0]["status"] == "cancelled"


def test_api_preflight_uses_structured_error_and_does_not_create_a_run(tmp_path, monkeypatch):
    async def missing(self):
        return {"status": "model_missing", "reason": "指定モデルが見つかりません"}

    monkeypatch.setattr(OllamaAdapter, "check", missing)
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1") as client:
        assert (
            client.post(
                "/api/models", json={"model_id": "missing", "name": "Missing", "backend": "ollama"}
            ).status_code
            == 200
        )
        frozen = client.post(
            "/api/sets", json={"generator_ids": ["math.linear"], "count": 2, "fixed_ratio": 0}
        ).json()
        response = client.post(
            "/api/runs",
            json={"set_id": frozen["set_id"], "model_ids": ["mock-reference", "missing"]},
        )
        assert response.status_code == 409
        assert response.json()["code"] == "execution_unavailable"
        assert client.get("/api/runs").json() == []
        assert client.get("/api/execution-blocks").json() == []
