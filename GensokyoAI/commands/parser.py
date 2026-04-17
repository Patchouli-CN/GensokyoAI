# GensokyoAI/commands/parser.py
"""命令解析器 - 从 utils 移动过来并简化"""

import re
from typing import Callable
from enum import Enum, auto
from msgspec import field, Struct


class CommandType(Enum):
    """命令类型"""

    SYSTEM = auto()  # 系统命令 (exit, save, etc.)
    CHAT = auto()  # 聊天命令 (think, whisper)
    PROMPT = auto()  # 提示词命令 (know, meta, attention)
    CUSTOM = auto()  # 自定义命令
    NONE = auto()  # 不是命令


class TagDefinition:
    """标签定义"""

    def __init__(
        self,
        name: str,
        aliases: list[str] | None = None,
        cmd_type: CommandType = CommandType.CUSTOM,
        description: str = "",
        handler: Callable | None = None,
    ):
        self.name = name
        self.aliases = aliases or []
        self.type = cmd_type
        self.description = description
        self.handler = handler

    @property
    def all_names(self) -> list[str]:
        return [self.name] + self.aliases


class ParsedCommand(Struct):
    """解析后的命令"""

    type: CommandType
    name: str
    content: str = ""
    args: list[str] = field(default_factory=list)
    raw: str = ""

    def get_text(self) -> str:
        return self.content or " ".join(self.args)


class CommandParser:
    """命令解析器 - 支持标签和前缀两种模式"""

    def __init__(self, mode: str = "smart"):
        self.mode = mode
        self._tags: dict[str, TagDefinition] = {}
        self._prefix_commands: dict[str, TagDefinition] = {}

    def register_tag(
        self,
        name: str,
        aliases: list[str] | None = None,
        cmd_type: CommandType = CommandType.CUSTOM,
        description: str = "",
        handler: Callable | None = None,
    ) -> "CommandParser":
        """注册标签命令 <tag>content</tag>"""
        tag = TagDefinition(name, aliases, cmd_type, description, handler)
        for n in tag.all_names:
            self._tags[n.lower()] = tag
        return self

    def register_prefix(
        self,
        name: str,
        aliases: list[str] | None = None,
        cmd_type: CommandType = CommandType.CUSTOM,
        description: str = "",
        handler: Callable | None = None,
    ) -> "CommandParser":
        """注册前缀命令 /command"""
        tag = TagDefinition(name, aliases, cmd_type, description, handler)
        for n in tag.all_names:
            self._prefix_commands[n.lower()] = tag
        return self

    def unregister(self, name: str) -> bool:
        """注销命令"""
        name = name.lower()
        removed = False
        if name in self._tags:
            del self._tags[name]
            removed = True
        if name in self._prefix_commands:
            del self._prefix_commands[name]
            removed = True
        return removed

    def get_tag(self, name: str) -> TagDefinition | None:
        return self._tags.get(name.lower())

    def parse(self, text: str) -> list[ParsedCommand]:
        """解析文本中的所有命令"""
        commands = []

        # 1. 解析标签模式 <tag>content</tag> 和 <tag content />
        tag_pattern = r"<([^>\s]+)(?:\s+([^>]+?))?\s*(?:>(.*?)</\1>|/>)"

        for match in re.finditer(tag_pattern, text, re.IGNORECASE | re.DOTALL):
            tag_name = match.group(1).lower()
            tag_args = match.group(2) or ""
            tag_content = match.group(3) or ""

            if tag_def := self._tags.get(tag_name):
                content = tag_content if tag_content else tag_args
                cmd = ParsedCommand(
                    type=tag_def.type,
                    name=tag_name,
                    content=content.strip(),
                    args=[content.strip()] if content else [],
                    raw=match.group(0),
                )
                commands.append(cmd)

        # 2. 解析前缀模式 /command args
        if self.mode in ("prefix", "smart"):
            lines = text.split("\n")
            for line in lines:
                line = line.strip()
                if line.startswith("/"):
                    parts = line[1:].split(maxsplit=1)
                    cmd_name = parts[0].lower()

                    if tag_def := self._prefix_commands.get(cmd_name):
                        content = parts[1] if len(parts) > 1 else ""
                        cmd = ParsedCommand(
                            type=tag_def.type,
                            name=cmd_name,
                            content=content,
                            args=[content] if content else [],
                            raw=line,
                        )
                        commands.append(cmd)

        return commands

    def parse_first(self, text: str) -> ParsedCommand | None:
        """解析第一个命令"""
        commands = self.parse(text)
        return commands[0] if commands else None

    def extract_clean_text(self, text: str) -> str:
        """提取纯文本（移除所有命令标签）"""
        # 移除标签
        tag_pattern = r"<[^>]+>.*?</[^>]+>|<[^>]+/>"
        text = re.sub(tag_pattern, "", text, flags=re.DOTALL)

        # 移除前缀命令行
        if self.mode in ("prefix", "smart"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("/")]
            text = "\n".join(lines)

        return text.strip()

    def has_prompt_commands(self, text: str) -> bool:
        """是否包含提示词命令"""
        return any(cmd.type == CommandType.PROMPT for cmd in self.parse(text))

    def extract_prompt_context(self, text: str) -> str:
        """提取提示词上下文"""
        context_parts = []
        for cmd in self.parse(text):
            if cmd.type == CommandType.PROMPT:
                context_parts.append(f"【{cmd.name.upper()}】\n{cmd.content}")
        return "\n\n".join(context_parts)
