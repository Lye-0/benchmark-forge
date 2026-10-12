import httpx
import pytest

from llm_benchmark.adapters import AdapterError, OllamaAdapter
from llm_benchmark.domain import ModelConfig
from llm_benchmark.runner import Scheduler, summarize
from llm_benchmark.tool_eval import ToolConfig, World, build_tool_set, evaluate_tools


@pytest.mark.parametrize("mode", ["native-tools", "agent"])
async def test_tool_modes_reset_world_and_record_trace(store, mode):
    frozen = build_tool_set(ToolConfig(mode=mode, count=5))
    assert frozen.set_hash == build_tool_set(ToolConfig(mode=mode, count=5)).set_hash
    assert "simulation" not in frozen.problems[0].public().model_dump()
    store.save_set(frozen)
    scheduler = Scheduler(store)
    scheduler.start()
    try:
        ids = scheduler.create(frozen.set_id, ["mock-reference", "mock-wrong"])
        await scheduler.queue.join()
        reports = [summarize(store, id) for id in ids]
        assert [r["correct"] for r in reports] == [5, 0]
        assert reports[0]["results"][0]["metrics"]["mode"] == mode
        assert reports[1]["results"][0]["metrics"]["policy_violation"]
        assert all(a["status"] == "correct" for a in reports[0]["attempts"])
    finally:
        await scheduler.close()


def test_tool_permissions_schema_and_reset():
    world = World("safe", 10)
    for name, args in [
        ("inventory.delete", {"item_id": "safe"}),
        ("inventory.lookup", {"item_id": "other"}),
        ("inventory.adjust", {"item_id": "safe", "delta": 5}),
    ]:
        with pytest.raises(ValueError):
            world.call(name, args)
        assert world.quantity == 10
    world.call("inventory.lookup", {"item_id": "safe"})
    for delta in [True, 1.2, 101, -11]:
        with pytest.raises(ValueError):
            world.call("inventory.adjust", {"item_id": "safe", "delta": delta})
    world.call("inventory.adjust", {"item_id": "safe", "delta": 3})
    assert world.quantity == 13
    assert World("safe", 10).quantity == 10


def test_unsupported_native_models_rejected_before_run(store):
    frozen = build_tool_set(ToolConfig())
    store.save_set(frozen)
    store.save_model(ModelConfig(model_id="text", name="Text", backend="ollama"))
    scheduler = Scheduler(store)
    with pytest.raises(AdapterError):
        scheduler.create(frozen.set_id, ["mock-reference", "text"])
    assert store.runs() == []


async def test_ollama_native_wire_contract():
    async def handler(request):
        import json

        data = json.loads(request.content)
        assert data["tools"][0]["function"]["name"] == "inventory.lookup"
        assert data["options"]["num_ctx"] == 2048
        assert "answer_spec" not in request.content.decode()
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {"function": {"name": "inventory.lookup", "arguments": {"item_id": "x"}}}
                    ],
                }
            },
        )

    adapter = OllamaAdapter(
        ModelConfig(
            model_id="native",
            name="Native",
            backend="ollama",
            context_length=2048,
            native_tools=True,
        ),
        httpx.MockTransport(handler),
    )
    from llm_benchmark.tool_eval import TOOLS

    response = await adapter.tool_turn([{"role": "user", "content": "public"}], TOOLS)
    assert response["tool_calls"][0]["function"]["name"] == "inventory.lookup"


async def test_tool_turn_limit_and_invalid_final(monkeypatch):
    async def repeated(config, messages, agent):
        return {
            "tool_calls": [
                {
                    "function": {
                        "name": "inventory.lookup",
                        "arguments": {"item_id": world["item_id"]},
                    }
                }
            ]
        }

    p = build_tool_set(ToolConfig(mode="agent", count=1)).problems[0]
    world = p.simulation
    monkeypatch.setattr("llm_benchmark.tool_eval.turn", repeated)
    response = await evaluate_tools(ModelConfig(model_id="m", name="m", backend="mock"), p, "agent")
    assert response.text == "TURN_LIMIT"
    assert response.metrics["tool_calls"] == 6
