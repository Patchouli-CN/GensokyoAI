"""工具结构化错误契约。"""

from __future__ import annotations

from msgspec import Struct, field
from typing import Any


class ToolError(Struct):
    """工具错误的双层结构。

    technical_message 给日志/模型诊断使用；user_message 给调用方/UI 展示使用。
    """

    error_code: str
    technical_message: str
    user_message: str
    recoverable: bool = True
    action_hint: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "technical_message": self.technical_message,
            "user_message": self.user_message,
            "recoverable": self.recoverable,
            "action_hint": self.action_hint,
            "details": dict(self.details),
        }


class ToolExecutionError(Exception):
    """携带结构化 ToolError 的工具执行异常。"""

    def __init__(self, error: ToolError):
        super().__init__(error.technical_message)
        self.error = error


__all__ = ["ToolError", "ToolExecutionError"]
