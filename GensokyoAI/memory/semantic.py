"""语义记忆 - 话题感知模式，零 embedding 显存占用"""

from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .topic_store import TopicAwareStore
from ..core.config import MemoryConfig
from ..utils.logging import logger

if TYPE_CHECKING:
    from ..core.agent.model_client import ModelClient
    from .types import Topic


class SemanticMemoryManager:
    """语义记忆管理器"""

    def __init__(
        self,
        config: MemoryConfig,
        character_id: str,
        memory_path: Path,  # 🆕 直接传完整路径
        model_client: "ModelClient",
    ):
        self.config = config
        self.character_id = character_id
        self._model_client = model_client
        self._enabled = config.semantic_enabled

        # 🆕 直接使用传入的路径
        store_path = memory_path / "topics.json"
        self._store = TopicAwareStore(
            store_path, 
            max_topics=50,
            topic_config=config.topic_generation
        )

        logger.debug(f"语义记忆初始化: {character_id}, 存储路径: {store_path}")

    async def add_async(
        self,
        content: str,
        importance: float = 0.0,
        tags: Optional[list[str]] = None,
    ) -> Optional["Topic"]:
        """添加语义记忆"""
        if not self._enabled:
            return None

        topic = await self._store.add_async(
            content=content,
            importance=importance,
            model_client=self._model_client,
        )

        if topic:
            logger.debug(f"添加语义记忆: {content[:30]}... -> 话题「{topic.name}」")
            return topic

        return None

    def get_relevant_context(self, query: str, top_k: int = 3) -> list[str]:
        """获取相关上下文（同步，兼容旧接口）"""
        if not self._enabled:
            return []

        results = self._store.search(query_text=query, top_k=top_k)

        contexts = []
        for item in results:
            if item.get("importance", 0) > 0.3:
                contexts.append(item.get("content", ""))

        return contexts

    async def get_relevant_context_async(self, query: str, top_k: int = 3) -> list[str]:
        """获取相关上下文（异步）"""
        if not self._enabled:
            return []

        results = self._store.search(query_text=query, top_k=top_k)
        return [item.get("content", "") for item in results[:top_k]]

    def get_topic_graph(self) -> dict:
        """获取话题关联图"""
        return self._store.get_topic_graph()

    @property
    def store(self):
        """暴露存储实例（供工具使用）"""
        return self._store

    @property
    def topic_count(self) -> int:
        return self._store.topic_count

    @property
    def memory_count(self) -> int:
        return self._store.memory_count
