#!/usr/bin/env python3
"""GensokyoAI CLI 入口 - 极简版"""

import asyncio
import argparse
from pathlib import Path

from rich.console import Console

from GensokyoAI.core.agent import Agent
from GensokyoAI.core.config import ConfigLoader
from GensokyoAI.backends.console import ConsoleBackendBuilder
from GensokyoAI.utils.exec_hook import set_exechook

# 灵梦，这是异变啊！
# 灵梦：嗯？让我看看，这也不是没啥事吗？（喝茶）
set_exechook()

console = Console()

def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="GensokyoAI - 幻想乡 AI 角色扮演引擎")

    parser.add_argument("--new-session", action="store_true", help="创建新会话")
    parser.add_argument("--resume", type=str, metavar="SESSION_ID", help="恢复指定会话")
    parser.add_argument("--character", "-c", type=str, help="角色名称或角色配置文件路径")
    parser.add_argument("--config", type=str, default="config/default.yaml", help="配置文件路径")
    parser.add_argument("--list-sessions", action="store_true", help="列出所有会话")
    parser.add_argument("--no-stream", action="store_true", help="禁用流式输出")

    return parser.parse_args()


def find_character_file(name: str) -> Path:
    """查找角色配置文件"""
    characters_dir = Path(__file__).parent / "characters"
    candidates = [
        characters_dir / f"{name}.yaml",
        characters_dir / f"{name}.yml",
        Path(name) if Path(name).exists() else None,
    ]

    for cand in candidates:
        if cand and cand.exists():
            return cand

    raise FileNotFoundError(f"找不到角色配置: {name}")


async def main():
    """主函数"""
    args = parse_args()

    # 加载配置
    config_file = Path(args.config) if args.config else None
    loader = ConfigLoader()
    config = loader.load(config_file)

    # 加载角色
    character_file = None
    if args.character:
        character_file = find_character_file(args.character)

    # 创建 Agent（会自动创建或加载会话）
    agent = Agent(config, config_file, character_file)

    # 会话管理
    if args.list_sessions:
        sessions = agent.session_manager.list_sessions()
        if sessions:
            console.print("[bold]历史会话:[/]")
            for sess in sessions:
                status = "●" if sess.is_active else "○"
                status_color = "green" if sess.is_active else "dim"
                console.print(
                    f"  [{status_color}]{status}[/] {sess.session_id[:8]}... - "
                    f"{sess.created_at.strftime('%Y-%m-%d %H:%M')} "
                    f"[yellow]({sess.total_turns} 轮)[/]"
                )
        else:
            console.print("[dim]没有历史会话[/]")
        return

    # 处理会话恢复/创建
    if args.resume:
        if agent.resume_session(args.resume):
            console.print(f"[green]✓ 已恢复会话: {args.resume[:8]}...[/]")
        else:
            console.print(f"[red]✗ 会话不存在: {args.resume}[/]")
            return
    elif args.new_session:
        # 🔧 --new-session 强制创建新会话，不复用
        session = agent.create_session()
        console.print(f"[green]✓ 已创建新会话: {session.session_id[:8]}...[/]")
    else:
        # 无参数：尝试恢复最近会话，否则创建新会话
        sessions = agent.session_manager.list_sessions()
        if sessions:
            latest = max(sessions, key=lambda s: s.last_active)
            agent.session_manager.set_current_session(latest.session_id)  # 👈 显式设置
            console.print(
                f"[green]✓ 已恢复历史会话: {latest.session_id[:8]}... ({latest.total_turns} 轮)[/]"
            )
        else:
            session = agent.create_session()  # 👈 内部会设置
            console.print(f"[green]✓ 新会话已就绪: {session.session_id[:8]}...[/]")

    # 构建并运行控制台后端
    backend = (
        ConsoleBackendBuilder(agent)
        .with_stream_mode(not args.no_stream)
        .with_color_theme(
            {
                "user": "bold #f5e6d3",
                "assistant": "bold #ffb7c5",
                "system": "dim #c9b1d4",
                "error": "bold #c41e3a",
                "success": "bold #98d8a8",
                "info": "#a4cde0",
                "cmd": "bold #d4a0d4",
                "prompt": "bold #ffe4a0",
            }
        )
        .build()
    )

    await backend.run_interactive()


if __name__ == "__main__":
    asyncio.run(main())
