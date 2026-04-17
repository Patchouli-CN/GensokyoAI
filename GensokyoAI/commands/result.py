# GensokyoAI/commands/result.py

from msgspec import Struct
from enum import Enum, auto
from typing import Any


class CommandStatus(Enum):
    """命令执行状态"""

    SUCCESS = auto()
    FAILURE = auto()
    NO_HANDLER = auto()


class CommandResult(Struct, frozen=False):
    """命令执行结果"""

    command: str
    status: CommandStatus
    message: str = ""
    data: Any = None
    should_exit: bool = False

    @classmethod
    def success(cls, command: str, message: str = "", data: Any = None) -> "CommandResult":
        return cls(command=command, status=CommandStatus.SUCCESS, message=message, data=data)

    @classmethod
    def failure(cls, command: str, message: str) -> "CommandResult":
        return cls(command=command, status=CommandStatus.FAILURE, message=message)

    @classmethod
    def no_handler(cls, command: str) -> "CommandResult":
        return cls(command=command, status=CommandStatus.NO_HANDLER, message=f"未知命令: {command}")

    @classmethod
    def exit(cls, message: str = "程序正在退出") -> "CommandResult":
        return cls(command="exit", status=CommandStatus.SUCCESS, message=message, should_exit=True)
