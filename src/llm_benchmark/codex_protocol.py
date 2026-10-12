"""Protocol-only integration; no live subprocess until isolation can be proven.

Source: official openai/codex app-server protocol, checked at a9b0815167c27ab13719dd12d13b63e02b70d221.
Transport is injected in tests. This does not provide sign-in or claim live compatibility.
"""

import asyncio
import json
from typing import Any, Protocol

from llm_benchmark.adapters import AdapterError
from llm_benchmark.domain import PublicProblem, Response


def parse_cli_events(lines: list[str], returncode: int) -> Response:
    if returncode != 0:
        raise AdapterError("Codex CLI失敗（認証・利用枠・プロセス状態を公式CLIで確認してください）")
    answers = []
    completed = False
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError as e:
            raise AdapterError("Codex CLIのJSONイベントが不正です") from e
        if event.get("type") in {"error", "turn.failed"}:
            raise AdapterError("Codex CLIエラーイベント")
        if event.get("type") == "item.completed":
            item = event.get("item", {})
            if item.get("type") == "agent_message":
                answers.append(item.get("text", ""))
            elif item.get("type") in {
                "command_execution",
                "file_change",
                "mcp_tool_call",
                "web_search",
            }:
                raise AdapterError("Codexのツール実行を検出したため評価を拒否しました")
        if event.get("type") == "turn.completed":
            completed = True
    if not completed or not answers:
        raise AdapterError("Codex CLIの完了イベントまたは回答が欠落しています")
    return Response(text="\n".join(answers))


class RpcTransport(Protocol):
    async def send(self, message: dict[str, Any]) -> None: ...
    async def receive(self) -> dict[str, Any]: ...


class AppServerSession:
    def __init__(self, transport: RpcTransport):
        self.transport = transport
        self.next_id = 0
        self.thread_id: str | None = None
        self.turn_id: str | None = None

    async def request(self, method: str, params: dict) -> dict:
        self.next_id += 1
        id = self.next_id
        await self.transport.send({"id": id, "method": method, "params": params})
        while True:
            message = await self.transport.receive()
            if message.get("id") == id and "method" not in message:
                if "error" in message:
                    raise AdapterError(f"Codex App Server要求失敗: {method}")
                return message.get("result", {})
            if "method" in message and "id" in message:
                # Never approve commands, file access, external tools or credential refresh.
                await self.transport.send(
                    {
                        "id": message["id"],
                        "error": {"code": -32601, "message": "Tools disabled in benchmark"},
                    }
                )
                raise AdapterError("許可されていないサーバー要求を拒否しました")

    async def complete(self, problem: PublicProblem, timeout: float = 30) -> Response:
        try:
            async with asyncio.timeout(timeout):
                await self.request(
                    "initialize",
                    {
                        "clientInfo": {"name": "benchmark_forge", "version": "0.1.0"},
                        "capabilities": {"experimentalApi": False},
                    },
                )
                await self.transport.send({"method": "initialized", "params": {}})
                account = await self.request("account/read", {"refreshToken": False})
                if account.get("account") is None:
                    raise AdapterError("Codex未認証。公式サインインと利用条件を確認してください")
                result = await self.request(
                    "thread/start",
                    {"ephemeral": True, "approvalPolicy": "never", "sandbox": "read-only"},
                )
                self.thread_id = result["thread"]["id"]
                result = await self.request(
                    "turn/start",
                    {
                        "threadId": self.thread_id,
                        "input": [{"type": "text", "text": problem.prompt}],
                    },
                )
                self.turn_id = result["turn"]["id"]
                answers = []
                while True:
                    event = await self.transport.receive()
                    if "id" in event and "method" in event:
                        await self.transport.send(
                            {
                                "id": event["id"],
                                "error": {"code": -32601, "message": "Tools disabled"},
                            }
                        )
                        raise AdapterError("ツール・認証要求はこの経路では許可されません")
                    method = event.get("method")
                    params = event.get("params", {})
                    event_turn_id = params.get("turnId") or params.get("turn", {}).get("id")
                    if params.get("threadId") != self.thread_id or event_turn_id != self.turn_id:
                        continue
                    if method == "error":
                        raise AdapterError("Codex通信または利用枠エラー")
                    if method == "item/completed":
                        item = params.get("item", {})
                        if item.get("type") == "agentMessage":
                            answers.append(item.get("text", ""))
                        elif item.get("type") not in {"reasoning"}:
                            raise AdapterError("テキスト回答以外の動作を検出しました")
                    if method == "turn/completed":
                        if params.get("turn", {}).get("status") != "completed":
                            raise AdapterError("Codexターンが正常に完了しませんでした")
                        return Response(text="\n".join(answers))
        except (TimeoutError, asyncio.CancelledError, AdapterError):
            if self.thread_id and self.turn_id:
                await self.transport.send(
                    {
                        "id": self.next_id + 1,
                        "method": "turn/interrupt",
                        "params": {"threadId": self.thread_id, "turnId": self.turn_id},
                    }
                )
            raise
