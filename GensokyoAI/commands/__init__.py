"""命令处理模块 - 纯抽象，不依赖任何后端"""

# GensokyoAI/commands/__init__.py

from .parser import CommandParser, CommandType, ParsedCommand
from .decorators import command, get_command, list_commands
from .executor import CommandExecutor
from .context import CommandContext
from .result import CommandResult, CommandStatus

__all__ = [
    "CommandParser",
    "CommandType",
    "ParsedCommand",
    "command",
    "CommandExecutor",
    "CommandContext",
    "CommandResult",
    "CommandStatus",
    "get_command",
    "list_commands",
]
