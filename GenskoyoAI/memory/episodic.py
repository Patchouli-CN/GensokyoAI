"""情景记忆 - 异步优化版"""

from typing import Optional
from datetime import datetime
import asyncio

import ollama

from .types import EpisodicMemory, MemoryRecord
from ..core.config import MemoryConfig
from ..utils.logging import logger
from ..utils.helpers import sync_to_async


class EpisodicMemoryManager:
    """情景记忆管理器"""

    def __init__(self, config: MemoryConfig, character_id: str, persistence=None):
        self.config = config
        self.character_id = character_id
        self._persistence = persistence
        self._episodes: list[EpisodicMemory] = []
        self._current_episode_messages: list[MemoryRecord] = []
        self._compress_lock = asyncio.Lock()  # 防止并发压缩

        # 创建异步版本的 ollama.chat
        self._ollama_chat_async = sync_to_async(ollama.chat)

        self._load()

    def _load(self) -> None:
        """加载历史情景记忆"""
        if self._persistence:
            self._episodes = self._persistence.load_episodes(self.character_id)
        logger.info(f"加载了 {len(self._episodes)} 条情景记忆")

    def add_message(self, record: MemoryRecord) -> None:
        """添加消息到当前情景（同步版本，触发异步压缩）"""
        self._current_episode_messages.append(record)

        # 检查是否需要压缩，异步触发
        if len(self._current_episode_messages) >= self.config.episodic_threshold:
            # 创建异步任务进行压缩，不阻塞当前线程
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.compress_async())
            except RuntimeError:
                # 没有运行中的事件循环，同步压缩
                self.compress()

    def compress(self) -> Optional[EpisodicMemory]:
        """压缩当前情景为摘要（同步版本，用于兼容）"""
        if len(self._current_episode_messages) < self.config.episodic_threshold:
            return None

        logger.info(f"开始压缩 {len(self._current_episode_messages)} 条消息...")

        keep_recent = self.config.episodic_keep_recent
        to_compress = (
            self._current_episode_messages[:-keep_recent]
            if keep_recent > 0
            else self._current_episode_messages
        )
        recent = (
            self._current_episode_messages[-keep_recent:] if keep_recent > 0 else []
        )

        summary = self._generate_summary_sync(to_compress)

        episode = EpisodicMemory(
            summary=summary,
            start_time=to_compress[0].timestamp if to_compress else datetime.now(),
            end_time=to_compress[-1].timestamp if to_compress else datetime.now(),
            message_count=len(to_compress),
            key_events=self._extract_key_events(to_compress),
        )

        self._episodes.append(episode)
        self._current_episode_messages = recent

        if self._persistence:
            self._persistence.save_episode(self.character_id, episode)

        logger.info(f"压缩完成，生成摘要长度: {len(summary)}")
        return episode

    async def compress_async(self) -> Optional[EpisodicMemory]:
        """压缩当前情景为摘要（异步版本）"""
        # 使用锁防止并发压缩
        async with self._compress_lock:
            if len(self._current_episode_messages) < self.config.episodic_threshold:
                return None

            logger.info(f"开始异步压缩 {len(self._current_episode_messages)} 条消息...")

            keep_recent = self.config.episodic_keep_recent
            to_compress = (
                self._current_episode_messages[:-keep_recent]
                if keep_recent > 0
                else self._current_episode_messages
            )
            recent = (
                self._current_episode_messages[-keep_recent:] if keep_recent > 0 else []
            )

            summary = await self._generate_summary_async(to_compress)

            episode = EpisodicMemory(
                summary=summary,
                start_time=to_compress[0].timestamp if to_compress else datetime.now(),
                end_time=to_compress[-1].timestamp if to_compress else datetime.now(),
                message_count=len(to_compress),
                key_events=self._extract_key_events(to_compress),
            )

            self._episodes.append(episode)
            self._current_episode_messages = recent

            if self._persistence:
                # 持久化可以异步处理
                asyncio.create_task(
                    self._persistence.save_episode_async(self.character_id, episode)
                )

            logger.info(f"异步压缩完成，生成摘要长度: {len(summary)}")
            return episode

    def _generate_summary_sync(self, messages: list[MemoryRecord]) -> str:
        """生成消息摘要（同步）"""
        conversation = []
        for m in messages:
            role_name = "用户" if m.role == "user" else "助手"
            conversation.append(f"{role_name}: {m.content}")

        text = "\n".join(conversation)

        prompt = f"""请将以下对话内容压缩为一个简短的摘要，保留关键信息和重要事件：

{text}

摘要："""

        try:
            response = ollama.chat(
                model=self.config.episodic_summary_model,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                options={"temperature": 0.3},
            )
            return response.message.content.strip()  # type: ignore
        except Exception as e:
            logger.error(f"生成摘要失败: {e}")
            return f"[压缩摘要] 共 {len(messages)} 条消息"

    async def _generate_summary_async(self, messages: list[MemoryRecord]) -> str:
        """生成消息摘要（异步）"""
        conversation = []
        for m in messages:
            role_name = "用户" if m.role == "user" else "助手"
            conversation.append(f"{role_name}: {m.content}")

        text = "\n".join(conversation)

        prompt = f"""请将以下对话内容压缩为一个简短的摘要，保留关键信息和重要事件：

{text}

摘要："""

        try:
            response = await self._ollama_chat_async(
                model=self.config.episodic_summary_model,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                options={"temperature": 0.3},
            )
            return response.message.content.strip()  # type: ignore
        except Exception as e:
            logger.error(f"生成摘要失败: {e}")
            return f"[压缩摘要] 共 {len(messages)} 条消息"

    def _extract_key_events(self, messages: list[MemoryRecord]) -> list[str]:
        """提取关键事件"""
        events = []
        for m in messages:
            if m.importance > 0.7 or len(m.content) > 100:
                events.append(m.content[:100])
        return events[-10:]

    def get_relevant_context(self, query: str, max_summaries: int = 3) -> list[str]:
        """获取相关的情景记忆上下文"""
        if not self._episodes:
            return []

        recent = self._episodes[-max_summaries:]
        return [e.summary for e in recent]

    def get_current_context(self) -> list[str]:
        """获取当前未压缩的消息"""
        return [m.content for m in self._current_episode_messages]
