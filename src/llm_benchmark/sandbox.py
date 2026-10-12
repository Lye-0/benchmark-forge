"""Fail closed. Docker presence alone never establishes a safe worker."""


class IsolationUnavailable(RuntimeError):
    pass


def sandbox_status() -> dict:
    return {
        "available": False,
        "code_execution": False,
        "agent_execution": False,
        "reason": "専用の隔離ワーカーと実侵入試験が未完了です。生成コード・ホストコマンドの実行は無効です。",
        "text_code_reading": True,
        "text_tool_selection": True,
        "native_tools": False,
        "multi_turn_agents": False,
    }


def execute_code(code: str) -> None:
    raise IsolationUnavailable(sandbox_status()["reason"])
