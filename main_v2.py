#!/usr/bin/env python3
"""GenskoyoAI CLI 入口 - 极简版"""

import asyncio
import argparse
from pathlib import Path

from rich.console import Console

from GenskoyoAI.core.agent import Agent
from GenskoyoAI.core.config import ConfigLoader
from GenskoyoAI.backends.console import ConsoleBackendBuilder


console = Console()


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="GenskoyoAI - 幻想乡 AI 角色扮演引擎")

    parser.add_argument("--new-session", action="store_true", help="创建新会话")
    parser.add_argument("--resume", type=str, metavar="SESSION_ID", help="恢复指定会话")
    parser.add_argument(
        "--character", "-c", type=str, help="角色名称或角色配置文件路径"
    )
    parser.add_argument(
        "--config", type=str, default="config/default.yaml", help="配置文件路径"
    )
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

    # 创建 Agent
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
            console.print(f"[green]已恢复会话: {args.resume[:8]}...[/]")
        else:
            console.print(f"[red]会话不存在: {args.resume}[/]")
            return
    elif args.new_session or not args.resume:
        agent.create_session()

    # 构建并运行控制台后端
    backend = (
        ConsoleBackendBuilder(agent)
        .with_stream_mode(not args.no_stream)
        .with_color_theme(
            {
                # 用户输入：柔和的米白色
                "user": "bold #f5e6d3",
                # 幽幽子的回复：樱花粉（她的代表色）
                "assistant": "bold #ffb7c5",
                # 系统消息：淡紫色（冥界的薄雾）
                "system": "dim #c9b1d4",
                # 错误消息：深红色（彼岸花）
                "error": "bold #c41e3a",
                # 成功消息：淡绿色（春之气息）
                "success": "bold #98d8a8",
                # 信息消息：淡蓝色（亡灵蝶）
                "info": "#a4cde0",
                # 命令：淡紫色（蝴蝶）
                "cmd": "bold #d4a0d4",
                # 提示词：淡金色（樱花下的月光）
                "prompt": "bold #ffe4a0",
            }
        )
        .build()
    )

    await backend.run_interactive()


if __name__ == "__main__":
    asyncio.run(main())
