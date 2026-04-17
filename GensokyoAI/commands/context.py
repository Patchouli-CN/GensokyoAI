# GensokyoAI/commands/context.py

from typing import TypeVar, Generic
from msgspec import Struct
from ..core.agent import Agent
from ..backends.base import BaseBackend


# 泛型变量
T = TypeVar("T", bound="BaseBackend")


class CommandContext(Struct, Generic[T], frozen=False):
    """
    命令执行上下文
    """

    agent: Agent | None = None
    backend: T | None = None
    source: str = "console"
    issuer: str = "Console"
    metadata: dict = {}

    @property
    def backend_inst(self) -> "T":
        """后端实例"""
        if self.backend is None:
            raise ValueError("Backend is not set")
        return self.backend

    @property
    def agent_inst(self) -> Agent:
        if self.agent is None:
            raise ValueError("Agent is not set")
        return self.agent
