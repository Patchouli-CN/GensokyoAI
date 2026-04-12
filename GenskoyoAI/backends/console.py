"""控制台后端 - 集成 Rich 美化"""

# GenskoyoAI/backends/console.py

from typing import Callable
import asyncio

from rich.console import Console as RichConsole
from rich.prompt import Prompt
from rich.panel import Panel
from rich.text import Text

from .base import BaseBackend
from ..core.agent import Agent
from ..utils.logging import logger
from ..utils.formatters import format_session_id, format_datetime
from ..utils.helpers import safe_get
from ..utils.cmd_parser import CommandParser, CommandHandler, ParsedCommand, CommandType


class ConsoleBackend(BaseBackend):
    """控制台后端 - 负责终端输入输出，使用 Rich 美化"""

    def __init__(self, agent: Agent):
        self.agent = agent
        self._stream_handler: Callable | None = None
        self._running = False
        self._use_stream = True
        self.console = RichConsole()

        # 初始化命令解析器
        self.cmd_parser = CommandParser(mode="smart")
        self.cmd_handler = CommandHandler(self.cmd_parser)

        # 注册命令处理器
        self._register_system_commands()
        self._register_chat_commands()
        self._register_prompt_commands()

        # 颜色配置
        self.colors = {
            "user": "bold green",
            "assistant": "bold yellow",
            "system": "dim",
            "error": "bold red",
            "success": "bold green",
            "info": "cyan",
            "cmd": "bold cyan",
            "prompt": "bold magenta",
        }

        # 累积的提示词上下文
        self._prompt_context: list[str] = []

    # ==================== 命令注册 ====================

    def _register_system_commands(self) -> None:
        """注册系统命令"""
        self.cmd_handler.register("exit", self._cmd_exit, CommandType.SYSTEM)
        self.cmd_handler.register("quit", self._cmd_exit, CommandType.SYSTEM)
        self.cmd_handler.register("back", self._cmd_back, CommandType.SYSTEM)
        self.cmd_handler.register("new", self._cmd_new, CommandType.SYSTEM)
        self.cmd_handler.register("save", self._cmd_save, CommandType.SYSTEM)
        self.cmd_handler.register("sessions", self._cmd_sessions, CommandType.SYSTEM)
        self.cmd_handler.register("help", self._cmd_help, CommandType.SYSTEM)
        self.cmd_handler.register("stream", self._cmd_stream, CommandType.SYSTEM)
        self.cmd_handler.register("clear", self._cmd_clear, CommandType.SYSTEM)

    def _register_chat_commands(self) -> None:
        """注册聊天命令"""
        self.cmd_handler.register("think", self._cmd_think, CommandType.CHAT)
        self.cmd_handler.register("whisper", self._cmd_whisper, CommandType.CHAT)
        self.cmd_handler.register("ooc", self._cmd_ooc, CommandType.CHAT)
        self.cmd_handler.register("describe", self._cmd_describe, CommandType.CHAT)
        self.cmd_handler.register("action", self._cmd_action, CommandType.CHAT)

    def _register_prompt_commands(self) -> None:
        """注册提示词命令"""
        self.cmd_handler.register("know", self._cmd_know, CommandType.PROMPT)
        self.cmd_handler.register("knowledge", self._cmd_know, CommandType.PROMPT)
        self.cmd_handler.register("meta", self._cmd_meta, CommandType.PROMPT)
        self.cmd_handler.register("metadata", self._cmd_meta, CommandType.PROMPT)
        self.cmd_handler.register("attention", self._cmd_attention, CommandType.PROMPT)
        self.cmd_handler.register("tips", self._cmd_attention, CommandType.PROMPT)

    def register_command(
        self,
        name: str,
        handler: Callable,
        cmd_type: CommandType = CommandType.CUSTOM,
        aliases: list[str] | None = None,
        description: str = "",
    ) -> "ConsoleBackend":
        """注册自定义命令"""
        self.cmd_parser.register_tag(name, aliases, cmd_type, description, handler)
        self.cmd_parser.register_prefix(name, aliases, cmd_type, description, handler)

        self.cmd_handler.register(name, handler, cmd_type)
        for alias in aliases or []:
            self.cmd_handler.register(alias, handler, cmd_type)

        return self

    # ==================== 系统命令处理器 ====================

    def _cmd_help(self, cmd: ParsedCommand) -> str:
        """显示帮助"""
        help_text = f"""
[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]
[bold cyan]  可用命令列表[/]
[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]

[bold yellow]系统命令:[/]
  • <cmd>exit</cmd>, /exit       - 退出程序
  • <cmd>back</cmd>, /back       - 回滚上一轮对话
  • <cmd>new</cmd>, /new         - 创建新会话
  • <cmd>save</cmd>, /save       - 保存当前会话
  • <cmd>sessions</cmd>          - 列出历史会话
  • <cmd>stream on/off</cmd>     - 切换流式输出
  • <cmd>clear</cmd>             - 清空提示词上下文
  • <cmd>help</cmd>, /help       - 显示此帮助

[bold magenta]提示词命令 (会传递给 AI):[/]
  • <know>内容</know>            - 提供参考资料
  • <meta>内容</meta>            - 提供元数据/场景设定
  • <attention>内容</attention>  - 提醒/纠正 AI

[bold green]聊天命令 (仅本地显示):[/]
  • <think>内容</think>          - 内心独白
  • <whisper>内容</whisper>      - 悄悄话
  • <ooc>内容</ooc>              - 场外发言
  • <describe>内容</describe>    - 描述场景
  • <action>内容</action>        - 执行动作

[dim]当前提示词上下文: {len(self._prompt_context)} 条[/]
[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]
"""
        self.console.print(help_text)
        return ""

    def _cmd_exit(self, cmd: ParsedCommand) -> str:
        """退出命令"""
        self._print_system_message("正在保存数据，再见！", style="info")
        self._running = False
        return "__EXIT__"

    def _cmd_back(self, cmd: ParsedCommand) -> str:
        """回滚命令"""
        self.agent.rollback(1)
        self._print_success_message("已回滚上一轮对话")
        return ""

    def _cmd_new(self, cmd: ParsedCommand) -> str:
        """新会话命令"""
        session = self.agent.create_session()
        self._prompt_context.clear()
        self._print_success_message(
            f"已创建新会话: {format_session_id(session.session_id)}"
        )
        if greeting := safe_get(self.agent.config, "character.greeting"):
            self._print_assistant_message(greeting)
        return ""

    def _cmd_save(self, cmd: ParsedCommand) -> str:
        """保存命令"""
        self.agent.session_handler.sync_save_current()
        self._print_success_message("会话已保存")
        return ""

    def _cmd_sessions(self, cmd: ParsedCommand) -> str:
        """列出会话命令"""
        sessions = self.agent.session_manager.list_sessions()
        self._show_sessions_panel(sessions)
        return ""

    def _cmd_stream(self, cmd: ParsedCommand) -> str:
        """切换流式输出"""
        if cmd.content:
            arg = cmd.content.lower()
            if arg in ("on", "true", "1", "enable"):
                self._use_stream = True
                self._print_success_message("流式输出已开启")
            elif arg in ("off", "false", "0", "disable"):
                self._use_stream = False
                self._print_success_message("流式输出已关闭")
            else:
                self._print_error_message(f"无效参数: {arg}，请使用 on/off")
        else:
            status = "开启" if self._use_stream else "关闭"
            self._print_info_message(f"流式输出当前: {status}")
        return ""

    def _cmd_clear(self, cmd: ParsedCommand) -> str:
        """清空提示词上下文"""
        count = len(self._prompt_context)
        self._prompt_context.clear()
        self._print_success_message(f"已清空 {count} 条提示词上下文")
        return ""

    # ==================== 聊天命令处理器 ====================

    def _cmd_think(self, cmd: ParsedCommand) -> str:
        if content := cmd.get_text():
            self.console.print(f"[dim italic]💭 {content}[/]")
        return ""

    def _cmd_whisper(self, cmd: ParsedCommand) -> str:
        if content := cmd.get_text():
            self.console.print(f"[dim]🤫 悄悄话: {content}[/]")
        return ""

    def _cmd_ooc(self, cmd: ParsedCommand) -> str:
        if content := cmd.get_text():
            self.console.print(f"[yellow]🎭 OOC: {content}[/]")
        return ""

    def _cmd_describe(self, cmd: ParsedCommand) -> str:
        if content := cmd.get_text():
            self.console.print(f"[cyan]📖 {content}[/]")
        return ""

    def _cmd_action(self, cmd: ParsedCommand) -> str:
        if content := cmd.get_text():
            self.console.print(f"[green]⚡ {content}[/]")
        return ""

    # ==================== 提示词命令处理器 ====================

    def _cmd_know(self, cmd: ParsedCommand) -> str:
        if content := cmd.get_text():
            self._prompt_context.append(f"【参考资料】\n{content}")
            self._print_success_message(f"已添加参考资料 ({len(content)} 字符)")
            self.console.print(
                f"[dim]📚 {content[:100]}{'...' if len(content) > 100 else ''}[/]"
            )
        return ""

    def _cmd_meta(self, cmd: ParsedCommand) -> str:
        if content := cmd.get_text():
            self._prompt_context.append(f"【场景设定】\n{content}")
            self._print_success_message(f"已添加场景设定 ({len(content)} 字符)")
            self.console.print(
                f"[dim]🎬 {content[:100]}{'...' if len(content) > 100 else ''}[/]"
            )
        return ""

    def _cmd_attention(self, cmd: ParsedCommand) -> str:
        if content := cmd.get_text():
            self._prompt_context.append(f"【重要提醒】\n{content}")
            self._print_success_message(f"已添加提醒 ({len(content)} 字符)")
            self.console.print(
                f"[bold yellow]⚠️ {content[:100]}{'...' if len(content) > 100 else ''}[/]"
            )
        return ""

    def _build_prompt_with_context(self, user_message: str) -> str:
        """构建带提示词上下文的完整消息"""
        if not self._prompt_context:
            return user_message

        context_text = "\n\n".join(self._prompt_context[-5:])
        return f"{context_text}\n\n【用户消息】\n{user_message}"

    # ==================== 核心方法 ====================

    async def start(self) -> None:
        """启动"""
        self._running = True
        logger.info("控制台后端已启动")

        self._show_welcome_panel()

        if greeting := safe_get(self.agent.config, "character.greeting"):
            self._print_assistant_message(greeting)

    def _show_welcome_panel(self) -> None:
        """显示欢迎面板"""
        character_name = safe_get(self.agent.config, "character.name", "Unknown")

        panel_content = Text()
        panel_content.append("幻想乡 AI 角色扮演引擎\n", style="bold magenta")
        panel_content.append(f"当前角色: {character_name}\n", style="cyan")
        panel_content.append("\n")
        panel_content.append("提示词标签: ", style="dim")
        panel_content.append("<know> ", style="bold magenta")
        panel_content.append("<meta> ", style="bold magenta")
        panel_content.append("<attention>\n", style="bold magenta")
        panel_content.append("输入 ", style="dim")
        panel_content.append("<cmd>help</cmd> ", style="bold cyan")
        panel_content.append("查看所有命令\n", style="dim")

        self.console.print(
            Panel(panel_content, title="✨ 欢迎 ✨", border_style="magenta")
        )

    def _show_sessions_panel(self, sessions: list) -> None:
        """显示会话列表面板"""
        if not sessions:
            self.console.print("[dim]没有历史会话[/]")
            return

        panel_content = Text()
        panel_content.append("历史会话\n", style="bold cyan")

        sorted_sessions = sorted(sessions, key=lambda s: s.created_at, reverse=True)

        for sess in sorted_sessions:
            session_id_short = format_session_id(sess.session_id)
            created_str = format_datetime(sess.created_at)
            status = "●" if sess.is_active else "○"
            status_color = "green" if sess.is_active else "dim"

            panel_content.append(f"  {status} ", style=status_color)
            panel_content.append(f"{session_id_short}", style="bold white")
            panel_content.append(f" - {created_str} ", style="dim")
            panel_content.append(f"({sess.total_turns} 轮)\n", style="yellow")

        self.console.print(Panel(panel_content, title="会话列表", border_style="cyan"))

    async def send(self, message: str) -> str:
        """发送消息并获取回复"""
        if not self._running or self.agent.is_shutting_down:
            return ""

        # 处理命令
        results, clean_text = await self.cmd_handler.handle(message)

        # 检查是否有退出命令
        if "__EXIT__" in results:
            return "__EXIT__"

        # 显示命令处理结果
        for result in results:
            if result and result != "__EXIT__":
                self.console.print(result)

        # 如果没有纯文本内容，不发送给 AI
        if not clean_text:
            return ""

        # 构建带上下文的完整消息
        full_message = self._build_prompt_with_context(clean_text)

        # 正常发送消息
        if self._use_stream and safe_get(self.agent.config, "model.stream", True):
            response = await self._send_stream(full_message)
        else:
            response = await self._send_non_stream(full_message)

        return response

    async def _send_stream(self, message: str) -> str:
        """流式发送并显示"""
        full_response = ""
        first_chunk = True

        character_name = safe_get(self.agent.config, "character.name", "Assistant")

        try:
            async for chunk in self.agent.send_stream(message):
                if self.agent.is_shutting_down:
                    break
                if chunk.is_tool_call and chunk.tool_info:
                    self._print_tool_call_indicator(chunk.tool_info)
                else:
                    if first_chunk:
                        self.console.print(
                            f"\n[{self.colors['assistant']}]{character_name}: [/]",
                            end="",
                        )
                        first_chunk = False

                    self.console.print(
                        chunk.content, end="", style=self.colors["assistant"]
                    )
                    full_response += chunk.content

                    if self._stream_handler:
                        self._stream_handler(chunk.content)

        except asyncio.CancelledError:
            logger.debug("流式输出被取消")
        except Exception as e:
            logger.error(f"流式输出错误: {e}")
            error_msg = f"[错误] {e}"
            self.console.print(f"\n{error_msg}", style=self.colors["error"])
            if not full_response:
                full_response = error_msg

        if not first_chunk:
            self.console.print()

        return full_response

    async def _send_non_stream(self, message: str) -> str:
        """非流式发送并显示"""
        character_name = safe_get(self.agent.config.character, "name", "Assistant")

        self.console.print(
            f"\n[{self.colors['assistant']}]{character_name}: [/]", end=""
        )
        self.console.print("思考中...", style="dim", end="\r")

        response = await self.agent.send(message)

        self.console.print(f"[{self.colors['assistant']}]{character_name}: [/]", end="")
        self.console.print(response, style=self.colors["assistant"])

        if self._stream_handler:
            self._stream_handler(response)

        if response:
            return response.content or ""
        
        return ""

    def _print_assistant_message(self, message: str) -> None:
        """打印助手消息"""
        character_name = safe_get(self.agent.config, "character.name", "Assistant")
        self.console.print()
        self.console.print(
            f"[{self.colors['assistant']}]{character_name}: [/]{message}"
        )

    def _print_system_message(self, message: str, style: str = "system") -> None:
        """打印系统消息"""
        self.console.print(f"[{self.colors.get(style, style)}]{message}[/]")

    def _print_success_message(self, message: str) -> None:
        """打印成功消息"""
        self._print_system_message(f"✓ {message}", style="success")

    def _print_error_message(self, message: str) -> None:
        """打印错误消息"""
        self._print_system_message(f"✗ {message}", style="error")

    def _print_info_message(self, message: str) -> None:
        """打印信息消息"""
        self._print_system_message(f"ℹ {message}", style="info")

    def _print_tool_call_indicator(self, tool_info: dict) -> None:
        """打印工具调用指示器"""
        if message := tool_info.get("message"):
            if hasattr(message, "tool_calls"):
                tool_names = [
                    tc.function.name
                    for tc in message.tool_calls
                    if hasattr(tc, "function")
                ]
                if tool_names:
                    logger.info(f"调用工具: {', '.join(tool_names)}")

    async def stop(self) -> None:
        """停止"""
        self._running = False
        self.agent.shutdown()
        logger.info("控制台后端已停止")

    def set_stream_handler(self, handler: Callable | None) -> None:
        """设置流式处理器"""
        self._stream_handler = handler

    def set_stream_mode(self, enabled: bool) -> None:
        """设置是否使用流式输出"""
        self._use_stream = enabled

    def set_color(self, element: str, color: str) -> None:
        """设置颜色主题"""
        if element in self.colors:
            self.colors[element] = color

    async def run_interactive(self) -> None:
        """运行交互式对话循环"""
        await self.start()

        self.console.print(
            "[dim]💡 输入 [/][bold cyan]<cmd>help</cmd>[/] [dim]查看所有命令[/]"
        )
        self.console.print("[dim]💡 按 Ctrl+C 安全退出（会自动保存）[/]\n")

        try:
            while self._running and not self.agent.is_shutting_down:
                try:
                    user_input = Prompt.ask(f"[{self.colors['user']}]你[/]")

                    if not user_input.strip():
                        continue

                    result = await self.send(user_input)

                    if result == "__EXIT__":
                        break

                except KeyboardInterrupt:
                    self.console.print("\n")
                    self._print_system_message("正在保存数据...", style="info")
                    break
                except EOFError:
                    break

        finally:
            self._print_system_message("正在保存会话数据...", style="info")
            await self.stop()
            self._print_success_message("数据已保存，再见！")


class ConsoleBackendBuilder:
    """控制台后端构建器 - 用于链式配置"""

    def __init__(self, agent: Agent):
        self._backend = ConsoleBackend(agent)

    def with_stream_mode(self, enabled: bool = True) -> "ConsoleBackendBuilder":
        self._backend.set_stream_mode(enabled)
        return self

    def with_stream_handler(self, handler: Callable) -> "ConsoleBackendBuilder":
        self._backend.set_stream_handler(handler)
        return self

    def with_color_theme(self, theme: dict[str, str]) -> "ConsoleBackendBuilder":
        for element, color in theme.items():
            self._backend.set_color(element, color)
        return self

    def register_command(
        self,
        name: str,
        handler: Callable,
        cmd_type: CommandType = CommandType.CUSTOM,
        aliases: list[str] | None = None,
        description: str = "",
    ) -> "ConsoleBackendBuilder":
        """注册自定义命令"""
        self._backend.register_command(name, handler, cmd_type, aliases, description)
        return self

    def build(self) -> ConsoleBackend:
        return self._backend
