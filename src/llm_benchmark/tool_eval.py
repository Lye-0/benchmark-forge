"""Native tool protocol and bounded multi-turn evaluation in a data-only virtual world."""

import asyncio
import json
import random
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from llm_benchmark.adapters import AdapterError, OllamaAdapter
from llm_benchmark.domain import (
    AnswerSpec,
    FrozenSet,
    ModelConfig,
    Problem,
    Response,
    SetConfig,
    StrictModel,
    canonical,
    digest,
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "inventory.lookup",
            "description": "Read quantity in a fictional inventory",
            "parameters": {
                "type": "object",
                "properties": {"item_id": {"type": "string"}},
                "required": ["item_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inventory.adjust",
            "description": "Add delta to quantity in the fictional inventory",
            "parameters": {
                "type": "object",
                "properties": {"item_id": {"type": "string"}, "delta": {"type": "integer"}},
                "required": ["item_id", "delta"],
                "additionalProperties": False,
            },
        },
    },
]


class ToolConfig(StrictModel):
    mode: Literal["native-tools", "agent"] = "native-tools"
    count: int = Field(default=5, ge=1, le=100)
    seed: int = Field(default=42, ge=0, le=2**32 - 1)


def build_tool_set(config: ToolConfig) -> FrozenSet:
    rng = random.Random(config.seed)
    problems = []
    for i in range(config.count):
        item, initial, target = (
            f"item-{rng.randrange(100000)}-{i}",
            rng.randrange(20),
            rng.randrange(20, 40),
        )
        data = {"item_id": item, "target_quantity": target}
        prompt = (
            (
                "inventory.lookupを1回だけ呼び出してitem_idの在庫を参照してください。"
                if config.mode == "native-tools"
                else "仮想在庫を参照してから調整し、item_idの在庫をtarget_quantityにしてください。達成後は「完了」と答えてください。その他の品目を変更してはいけません。"
            )
            + "\n"
            + canonical(data)
        )
        spec = (
            {"name": "inventory.lookup", "arguments": {"item_id": item}}
            if config.mode == "native-tools"
            else {"item_id": item, "quantity": target}
        )
        simulation = {"item_id": item, "initial_quantity": initial, "protected_quantity": 99}
        content = digest({"prompt": prompt, "simulation": simulation, "expected": spec})
        problems.append(
            Problem(
                problem_id="p-" + content[:24],
                generator_id="tool." + config.mode,
                generator_version="1.0.0",
                category_id="14",
                subcategory_id=config.mode,
                tags=["仮想世界"],
                seed=config.seed,
                target_difficulty=0,
                prompt=prompt,
                answer_spec=AnswerSpec(expected=spec, type="json"),
                grading_type="json",
                origin="dynamic",
                template="virtual-inventory-" + config.mode,
                features={},
                simulation=simulation,
                content_hash=content,
            )
        )
    settings = SetConfig(
        generator_ids=["tool." + config.mode],
        count=config.count,
        seed=config.seed,
        fixed_ratio=0,
        profile="tool-preview-v1",
        custom=True,
        evaluation_mode=config.mode,
    )
    weights = {p.problem_id: 1 / len(problems) for p in problems}
    hash = digest(
        {
            "config": settings.model_dump(),
            "problems": [p.model_dump() for p in problems],
            "weights": weights,
            "profile": "Tool preview v1",
        }
    )
    return FrozenSet(
        set_id="set-" + hash[:24],
        set_hash=hash,
        config=settings,
        problems=problems,
        weights=weights,
        profile_version="Tool preview v1",
        created_at=datetime.now(UTC).isoformat(),
        metadata={"mode": config.mode, "world": "in-memory-only", "max_turns": 6},
        warnings=[
            "独立したツール評価。テキスト型の選択問題や通常の能力スコアと混合しません。",
            "仮想在庫は問題ごとに初期化。外部API・OS・実ファイルへの操作はありません。",
        ],
        duplicate_stats={"adopted": len(problems)},
    )


class World:
    def __init__(self, item: str, quantity: int):
        self.item = item
        self.quantity = quantity
        self.read = False
        self.calls = 0

    def call(self, name: str, arguments: dict) -> dict:
        self.calls += 1
        if arguments.get("item_id") != self.item:
            raise ValueError("許可外の品目")
        if name == "inventory.lookup" and set(arguments) == {"item_id"}:
            self.read = True
        elif name == "inventory.adjust" and set(arguments) == {"item_id", "delta"}:
            delta = arguments["delta"]
            if (
                not self.read
                or type(delta) is not int
                or abs(delta) > 100
                or self.quantity + delta < 0
            ):
                raise ValueError("参照前の変更・不正な引数")
            self.quantity += delta
        else:
            raise ValueError("未許可のツールまたは引数")
        return {"item_id": self.item, "quantity": self.quantity}


async def turn(config: ModelConfig, messages: list[dict], *, agent: bool) -> dict:
    if config.backend == "mock":
        if config.mock_behavior == "timeout":
            await asyncio.sleep(config.timeout_seconds + 1)
        if config.mock_behavior == "error":
            raise AdapterError("意図的なMockツール通信エラー")
        if config.mock_behavior == "empty":
            return {"content": ""}
        data = json.loads(messages[0]["content"].splitlines()[-1])
        if config.mock_behavior == "wrong":
            return {
                "tool_calls": [
                    {
                        "function": {
                            "name": "inventory.delete",
                            "arguments": {"item_id": data["item_id"]},
                        }
                    }
                ]
            }
        if len(messages) == 1:
            return {
                "tool_calls": [
                    {
                        "function": {
                            "name": "inventory.lookup",
                            "arguments": {"item_id": data["item_id"]},
                        }
                    }
                ]
            }
        if len(messages) == 3:
            current = json.loads(messages[-1]["content"])["quantity"]
            return {
                "tool_calls": [
                    {
                        "function": {
                            "name": "inventory.adjust",
                            "arguments": {
                                "item_id": data["item_id"],
                                "delta": data["target_quantity"] - current,
                            },
                        }
                    }
                ]
            }
        return {"content": "完了"}
    if config.backend != "ollama" or not config.native_tools:
        raise AdapterError("このモデル設定ではネイティブツール評価を利用できません")
    adapter = OllamaAdapter(config)
    return await adapter.tool_turn(messages, TOOLS if agent else TOOLS[:1])


async def evaluate_tools(config: ModelConfig, problem: Problem, mode: str) -> Response:
    public = problem.public()
    messages = [{"role": "user", "content": public.prompt}]
    world = World(problem.simulation["item_id"], problem.simulation["initial_quantity"])
    trace = []
    for step in range(6):
        message = await turn(config, messages, agent=mode == "agent")
        # Only a bounded transcript is retained; never execute arbitrary tool names.
        if len(canonical(message)) > 64000:
            raise AdapterError("ツール応答が大きすぎます")
        calls = message.get("tool_calls", [])
        trace.append({"turn": step + 1, "message": message})
        if not calls:
            success = mode == "agent" and world.read and message.get("content") == "完了"
            return Response(
                text=canonical({"item_id": world.item, "quantity": world.quantity})
                if success
                else "FINAL_ANSWER_INVALID",
                metrics={
                    "mode": mode,
                    "tool_calls": world.calls,
                    "turns": step + 1,
                    "trace": trace,
                    "final_answer_valid": success,
                },
            )
        if not isinstance(calls, list) or len(calls) != 1:
            return Response(text="TOOL_SCHEMA_INVALID", metrics={"mode": mode, "trace": trace})
        try:
            fn = calls[0]["function"]
            if set(fn) != {"name", "arguments"} or not isinstance(fn["arguments"], dict):
                raise ValueError("schema")
            if mode == "native-tools":
                if fn["name"] != "inventory.lookup":
                    raise ValueError("tool selection")
                world.call(fn["name"], fn["arguments"])
                return Response(
                    text=canonical(fn), metrics={"mode": mode, "tool_calls": 1, "trace": trace}
                )
            outcome = world.call(fn["name"], fn["arguments"])
        except (KeyError, TypeError, ValueError):
            return Response(
                text="TOOL_POLICY_VIOLATION",
                metrics={
                    "mode": mode,
                    "tool_calls": world.calls,
                    "trace": trace,
                    "policy_violation": True,
                },
            )
        messages.append({"role": "assistant", **message})
        messages.append({"role": "tool", "tool_name": fn["name"], "content": canonical(outcome)})
    return Response(
        text="TURN_LIMIT", metrics={"mode": mode, "tool_calls": world.calls, "trace": trace}
    )
