# GensokyoAI/backends/console/commands.py

"""ConsoleBackend 的命令处理器"""

from typing import TYPE_CHECKING

from ...commands import command, CommandType, CommandContext, CommandResult, CommandExecutor
from ...utils.formatters import format_session_id
from ...utils.helpers import safe_get

if TYPE_CHECKING:
    from ._impl import ConsoleBackend


# ==================== 系统命令 ====================


@command(name="exit", cmd_type=CommandType.SYSTEM, aliases=["quit"], description="退出程序")
async def cmd_exit(ctx: CommandContext) -> CommandResult:
    """退出程序"""
    backend: "ConsoleBackend" = ctx.backend_inst
    backend._print_system_message("正在保存数据，再见！", style="info")
    backend._running = False
    return CommandResult.exit()


@command(name="back", cmd_type=CommandType.SYSTEM, description="回滚上一轮对话")
async def cmd_back(ctx: CommandContext) -> CommandResult:
    """回滚对话"""
    ctx.agent_inst.rollback(1)
    return CommandResult.success("back", "已回滚上一轮对话")

@command(name="new", cmd_type=CommandType.SYSTEM, description="创建新会话")
async def cmd_new(ctx: CommandContext) -> CommandResult:
    """创建新会话"""
    backend: "ConsoleBackend" = ctx.backend_inst
    session = ctx.agent_inst.create_session()
    backend._prompt_context.clear()
    session_id_short = format_session_id(session.session_id)

    if greeting := safe_get(ctx.agent_inst.config, "character.greeting"):
        backend._print_assistant_message(greeting)

    return CommandResult.success("new", f"已创建新会话: {session_id_short}")


@command(name="save", cmd_type=CommandType.SYSTEM, description="保存当前会话")
async def cmd_save(ctx: CommandContext) -> CommandResult:
    """保存会话"""
    await ctx.agent_inst.async_save()
    return CommandResult.success("save", "会话已保存")


@command(name="sessions", cmd_type=CommandType.SYSTEM, description="列出历史会话")
async def cmd_sessions(ctx: CommandContext) -> CommandResult:
    """列出会话"""
    backend: "ConsoleBackend" = ctx.backend_inst
    sessions = ctx.agent_inst.session_manager.list_sessions()
    backend._show_sessions_panel(sessions)
    return CommandResult.success("sessions", f"共 {len(sessions)} 个历史会话")


@command(name="stream", cmd_type=CommandType.SYSTEM, description="切换流式输出")
async def cmd_stream(ctx: CommandContext, mode: str = "toggle") -> CommandResult:
    """切换流式输出"""
    backend: "ConsoleBackend" = ctx.backend_inst

    if mode in ("on", "true", "1", "enable"):
        backend._use_stream = True
        return CommandResult.success("stream", "流式输出已开启")
    elif mode in ("off", "false", "0", "disable"):
        backend._use_stream = False
        return CommandResult.success("stream", "流式输出已关闭")
    elif mode == "toggle":
        backend._use_stream = not backend._use_stream
        status = "开启" if backend._use_stream else "关闭"
        return CommandResult.success("stream", f"流式输出已切换为: {status}")
    else:
        status = "开启" if backend._use_stream else "关闭"
        return CommandResult.success("stream", f"流式输出当前: {status}")


@command(name="clear", cmd_type=CommandType.SYSTEM, description="清空提示词上下文")
async def cmd_clear(ctx: CommandContext) -> CommandResult:
    """清空提示词上下文"""
    backend: "ConsoleBackend" = ctx.backend_inst
    count = len(backend._prompt_context)
    backend._prompt_context.clear()
    return CommandResult.success("clear", f"已清空 {count} 条提示词上下文")

@command(name="errors", cmd_type=CommandType.SYSTEM, description="查看最近错误")
async def cmd_errors(ctx: CommandContext) -> CommandResult:
    """查看系统错误状态"""
    backend: "ConsoleBackend" = ctx.backend_inst
    agent = ctx.agent_inst
    
    backend.console.print("[bold red]📊 错误统计[/]")
    
    if hasattr(agent, 'error_listeners'):
        stats = agent.error_listeners.get_error_stats()
        backend.console.print(f"总错误数: {stats['total']}")
        
        if stats['counts']:
            backend.console.print("\n[bold]按类型:[/]")
            for key, count in stats['counts'].items():
                backend.console.print(f"  • {key}: {count}")
        else:
            backend.console.print("  [dim]暂无错误记录[/]")
        
        if stats['recent']:
            backend.console.print("\n[bold]最近错误:[/]")
            for err in stats['recent'][-5:]:
                ts = err['timestamp'].strftime("%H:%M:%S")
                status = f"[{err.get('status_code', 'N/A')}]" if err.get('status_code') else ""
                error_preview = err['error'][:50] + "..." if len(err['error']) > 50 else err['error']
                backend.console.print(f"  • {ts} {status} {error_preview}")
    else:
        backend.console.print("[dim]错误监听器未初始化[/]")
    
    # 🆕 显示 EventBus 状态
    if hasattr(agent, 'event_bus'):
        stats = agent.event_bus.stats
        backend.console.print(f"\n[bold]EventBus 状态:[/]")
        backend.console.print(f"  已发布: {stats['published']}, 已投递: {stats['delivered']}, 错误: {stats['errors']}")
    
    return CommandResult.success("errors", "错误已显示")


@command(name="help", cmd_type=CommandType.SYSTEM, description="显示帮助信息")
async def cmd_help(ctx: CommandContext) -> CommandResult:
    """显示帮助"""
    backend: "ConsoleBackend" = ctx.backend_inst

    executor = CommandExecutor()
    commands = executor.list_commands()

    help_text = """
[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]
[bold cyan]  可用命令列表[/]
[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]

[bold yellow]系统命令:[/]
"""
    for cmd in commands:
        if cmd.type == CommandType.SYSTEM:
            aliases = f" ({', '.join(cmd.aliases)})" if cmd.aliases else ""
            help_text += f"  • <cmd>{cmd.name}</cmd>, /{cmd.name}{aliases} - {cmd.description}\n"
            help_text += f"    [dim]用法: {cmd.usage}[/]\n"

    help_text += "\n[bold magenta]提示词命令 (会传递给 AI):[/]\n"
    for cmd in commands:
        if cmd.type == CommandType.PROMPT:
            aliases = f" ({', '.join(cmd.aliases)})" if cmd.aliases else ""
            help_text += f"  • <{cmd.name}>内容</{cmd.name}>{aliases} - {cmd.description}\n"

    help_text += "\n[bold green]聊天命令 (仅本地显示):[/]\n"
    for cmd in commands:
        if cmd.type == CommandType.CHAT:
            help_text += f"  • <{cmd.name}>内容</{cmd.name}> - {cmd.description}\n"

    help_text += f"\n[dim]当前提示词上下文: {len(backend._prompt_context)} 条[/]"
    help_text += "\n[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]"

    backend.console.print(help_text)

    return CommandResult.success("help", "帮助信息已显示")


# ==================== 聊天命令 ====================

_CHAT_ICONS = {
    "think": "💭",
    "whisper": "🤫 悄悄话:",
    "ooc": "🎭 OOC:",
    "describe": "📖",
    "action": "⚡",
}

_CHAT_COLORS = {
    "think": "dim italic",
    "whisper": "dim",
    "ooc": "yellow",
    "describe": "cyan",
    "action": "green",
}


def _make_chat_handler(cmd_name: str):
    @command(name=cmd_name, cmd_type=CommandType.CHAT, description=f"{cmd_name} 命令")
    async def handler(ctx: CommandContext, content: str = "") -> CommandResult:
        if content:
            backend: "ConsoleBackend" = ctx.backend_inst
            icon = _CHAT_ICONS.get(cmd_name, "")
            color = _CHAT_COLORS.get(cmd_name, "white")
            backend.console.print(f"[{color}]{icon} {content}[/]")
        return CommandResult.success(cmd_name)

    return handler


# 注册聊天命令
cmd_think = _make_chat_handler("think")
cmd_whisper = _make_chat_handler("whisper")
cmd_ooc = _make_chat_handler("ooc")
cmd_describe = _make_chat_handler("describe")
cmd_action = _make_chat_handler("action")


# ==================== 提示词命令 ====================

_PROMPT_PREFIXES = {
    "know": "【参考资料】",
    "meta": "【场景设定】",
    "attention": "【重要提醒】",
}

_PROMPT_ICONS = {
    "know": "📚",
    "meta": "🎬",
    "attention": "⚠️",
}


def _make_prompt_handler(cmd_name: str):
    aliases_map = {
        "know": ["knowledge"],
        "meta": ["metadata"],
        "attention": ["tips"],
    }

    @command(
        name=cmd_name,
        cmd_type=CommandType.PROMPT,
        aliases=aliases_map.get(cmd_name, []),
        description=f"提供{cmd_name}信息给 AI",
    )
    async def handler(ctx: CommandContext, content: str = "") -> CommandResult:
        if content:
            backend: "ConsoleBackend" = ctx.backend_inst
            prefix = _PROMPT_PREFIXES.get(cmd_name, "")
            icon = _PROMPT_ICONS.get(cmd_name, "")
            backend._prompt_context.append(f"{prefix}\n{content}")

            preview = content[:100] + ("..." if len(content) > 100 else "")
            backend.console.print(f"[dim]{icon} {preview}[/]")

        return CommandResult.success(cmd_name, f"已添加{cmd_name}上下文 ({len(content)} 字符)")

    return handler


# 注册提示词命令
cmd_know = _make_prompt_handler("know")
cmd_meta = _make_prompt_handler("meta")
cmd_attention = _make_prompt_handler("attention")
