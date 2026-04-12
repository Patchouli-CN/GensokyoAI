"""智能命令解析器 - 支持可扩展标签"""

# GenskoyoAI\utils\cmd_parser.py

import re
from typing import Callable, Awaitable
from enum import Enum, auto
from msgspec import field, Struct
import inspect
from .logging import logger


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
        """所有可用名称"""
        return [self.name] + self.aliases


class ParsedCommand(Struct):
    """解析后的命令"""

    type: CommandType
    name: str
    content: str = ""  # 标签内的完整内容
    args: list[str] = field(default_factory=list)
    raw: str = ""

    _tag_def: TagDefinition | None = None

    def define_tag(self, tag_def: TagDefinition) -> None:
        """保存标签定义"""
        self._tag_def = tag_def

    def get_text(self) -> str:
        """获取内容文本（content 或 args 拼接）"""
        return self.content or " ".join(self.args)


class CommandParser:
    """命令解析器 - 支持可扩展标签"""

    def __init__(self, mode: str = "smart"):
        """
        初始化解析器

        Args:
            mode: 解析模式
                - "tag": 只解析标签模式 <tag>content</tag>
                - "prefix": 只解析前缀模式 /command
                - "smart": 智能混合模式
        """
        self.mode = mode
        self._tags: dict[str, TagDefinition] = {}
        self._prefix_commands: dict[str, TagDefinition] = {}

        # 注册内置标签
        self._register_builtin_tags()

    def _register_builtin_tags(self) -> None:
        """注册内置标签"""
        # 提示词标签（这些会传递给 AI）
        self.register_tag(
            "know",
            aliases=["knowledge"],
            cmd_type=CommandType.PROMPT,
            description="提供参考资料给 AI",
        )
        self.register_tag(
            "meta",
            aliases=["metadata"],
            cmd_type=CommandType.PROMPT,
            description="提供元数据（场景、设定等）",
        )
        self.register_tag(
            "attention",
            aliases=["tips"],
            cmd_type=CommandType.PROMPT,
            description="提醒/纠正 AI 的扮演",
        )

        # 系统命令标签
        self.register_tag(
            "cmd",
            aliases=["command"],
            cmd_type=CommandType.SYSTEM,
            description="执行系统命令",
        )
        self.register_prefix(
            "exit", cmd_type=CommandType.SYSTEM, description="退出程序"
        )
        self.register_prefix(
            "quit", cmd_type=CommandType.SYSTEM, description="退出程序"
        )
        self.register_prefix(
            "back", cmd_type=CommandType.SYSTEM, description="回滚对话"
        )
        self.register_prefix("new", cmd_type=CommandType.SYSTEM, description="新会话")
        self.register_prefix(
            "save", cmd_type=CommandType.SYSTEM, description="保存会话"
        )
        self.register_prefix(
            "sessions", cmd_type=CommandType.SYSTEM, description="列出会话"
        )
        self.register_prefix(
            "help", cmd_type=CommandType.SYSTEM, description="显示帮助"
        )

        # 聊天命令标签
        self.register_tag("think", cmd_type=CommandType.CHAT, description="内心独白")
        self.register_tag("whisper", cmd_type=CommandType.CHAT, description="悄悄话")
        self.register_tag("ooc", cmd_type=CommandType.CHAT, description="场外发言")
        self.register_tag("describe", cmd_type=CommandType.CHAT, description="描述场景")
        self.register_tag("action", cmd_type=CommandType.CHAT, description="执行动作")

    def register_tag(
        self,
        name: str,
        aliases: list[str] | None = None,
        cmd_type: CommandType = CommandType.CUSTOM,
        description: str = "",
        handler: Callable | None = None,
    ) -> "CommandParser":
        """注册标签命令

        Example:
            parser.register_tag("know", aliases=["knowledge"],
                               cmd_type=CommandType.PROMPT,
                               description="提供参考资料")
        """
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
        """注册前缀命令（/command 格式）"""
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
        """获取标签定义"""
        return self._tags.get(name.lower())

    def list_tags(self, cmd_type: CommandType | None = None) -> list[TagDefinition]:
        """列出所有标签"""
        tags = list(set(self._tags.values()))
        if cmd_type:
            tags = [t for t in tags if t.type == cmd_type]
        return tags

    def parse(self, text: str) -> list[ParsedCommand]:
        """解析文本中的所有命令

        Returns:
            解析出的命令列表（按出现顺序）
        """
        commands = []

        # 1. 解析标签模式 <tag>content</tag> 和 <tag content />
        tag_pattern = r"<([^>\s]+)(?:\s+([^>]+?))?\s*(?:>(.*?)</\1>|/>)"

        for match in re.finditer(tag_pattern, text, re.IGNORECASE | re.DOTALL):
            tag_name = match.group(1).lower()
            tag_args = match.group(2) or ""
            tag_content = match.group(3) or ""

            if tag_def := self._tags.get(tag_name):
                # 解析内容
                content = tag_content if tag_content else tag_args

                cmd = ParsedCommand(
                    type=tag_def.type,
                    name=tag_name,
                    content=content.strip(),
                    args=[content.strip()] if content else [],
                    raw=match.group(0),
                )
                cmd.define_tag(tag_def)  # 保存标签定义以便处理
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
                        cmd.define_tag(tag_def)
                        commands.append(cmd)

        return commands

    def parse_first(self, text: str) -> ParsedCommand | None:
        """解析第一个命令"""
        if commands := self.parse(text):
            return commands[0]
        return None

    def extract_prompt_context(self, text: str) -> str:
        """提取提示词上下文（用于发送给 AI）

        将 PROMPT 类型的标签转换为提示词格式
        """
        context_parts = []

        for cmd in self.parse(text):
            if cmd.type == CommandType.PROMPT:
                tag_def = getattr(cmd, "_tag_def", None)
                tag_display = tag_def.name.upper() if tag_def else cmd.name.upper()
                context_parts.append(f"【{tag_display}】\n{cmd.content}")

        return "\n\n".join(context_parts)

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


class CommandHandler:
    """命令处理器 - 支持动态注册"""

    def __init__(self, parser: CommandParser):
        self.parser = parser
        self._handlers: dict[str, tuple[Callable, CommandType]] = {}

        # 注册默认处理器
        self._register_defaults()

    def _register_defaults(self) -> None:
        """注册默认处理器"""
        # 可以从 parser 的标签定义中自动注册
        for tag in self.parser.list_tags():
            if tag.handler:
                self.register(tag.name, tag.handler, tag.type)

    def register(
        self,
        name: str,
        handler: Callable[[ParsedCommand], str | Awaitable[str]],
        cmd_type: CommandType = CommandType.CUSTOM,
    ) -> "CommandHandler":
        """注册命令处理器

        Args:
            name: 命令名称
            handler: 处理函数，接收 ParsedCommand，返回处理结果
            cmd_type: 命令类型
        """
        self._handlers[name.lower()] = (handler, cmd_type)
        return self

    def unregister(self, name: str) -> bool:
        """注销处理器"""
        if name.lower() in self._handlers:
            del self._handlers[name.lower()]
            return True
        return False

    async def handle(self, text: str) -> tuple[list[str], str]:
        """处理文本中的所有命令

        Returns:
            (处理结果列表, 清理后的文本)
        """
        commands = self.parser.parse(text)
        results = []

        for cmd in commands:
            if handler_info := self._handlers.get(cmd.name):
                handler, _ = handler_info
                try:
                    if inspect.iscoroutinefunction(handler):
                        result = await handler(cmd)
                    else:
                        result = handler(cmd)
                    results.append(result or "")
                except Exception as e:
                    logger.error(f"命令处理失败 [{cmd.name}]: {e}")
                    results.append(f"[错误] 命令执行失败: {e}")

        clean_text = self.parser.extract_clean_text(text)
        return results, clean_text

    def handle_sync(self, text: str) -> tuple[list[str], str]:
        """同步处理命令"""
        commands = self.parser.parse(text)
        results = []

        for cmd in commands:
            if handler_info := self._handlers.get(cmd.name):
                handler, _ = handler_info
                try:
                    result = handler(cmd)
                    results.append(result or "")
                except Exception as e:
                    logger.error(f"命令处理失败 [{cmd.name}]: {e}")

        clean_text = self.parser.extract_clean_text(text)
        return results, clean_text
