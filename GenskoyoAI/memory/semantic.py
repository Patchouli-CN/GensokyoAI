"""语义记忆 - 支持模型提取和向量检索双模式 - 异步优化版"""

import json
import asyncio
from pathlib import Path
from enum import Enum

import ollama
import numpy as np
import ayafileio

from .types import SemanticMemory
from ..core.config import MemoryConfig
from ..utils.logging import logger
from ..utils.helpers import sync_to_async


class SemanticMode(Enum):
    """语义记忆模式"""

    EMBEDDING = "embedding"
    MODEL_EXTRACT = "model_extract"
    DISABLED = "disabled"
    UNKNOWN = "unknown"  # 新增：未检测状态


class SimpleVectorStore:
    """简单的向量存储（使用 ayafileio 实现真异步）"""

    def __init__(self, path: Path):
        self.path = path
        self._data: list[dict] = []
        self._lock = asyncio.Lock()
        self._load_sync()

    def _load_sync(self) -> None:
        """同步加载（初始化时使用）"""
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except Exception as e:
                logger.warning(f"加载向量存储失败: {e}")
                self._data = []

    async def _load_async(self) -> None:
        """异步加载"""
        if self.path.exists():
            try:
                async with ayafileio.open(self.path, "r", encoding="utf-8") as f:
                    content = await f.read()
                    self._data = json.loads(content)
            except Exception as e:
                logger.warning(f"异步加载向量存储失败: {e}")
                self._data = []

    def _save_sync(self) -> None:
        """同步保存"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    async def _save_async(self) -> None:
        """异步保存"""
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            async with ayafileio.open(self.path, "w", encoding="utf-8") as f:
                content = json.dumps(self._data, ensure_ascii=False, indent=2)
                await f.write(content)

    def add(self, item: dict) -> None:
        """同步添加"""
        self._data.append(item)
        self._save_sync()

    async def add_async(self, item: dict) -> None:
        """异步添加"""
        async with self._lock:
            self._data.append(item)
            await self._save_async()

    def search(self, query_embedding: list[float], top_k: int = 5) -> list[dict]:
        """余弦相似度搜索"""
        if not self._data:
            return []

        try:
            query_vec = np.array(query_embedding)

            results = []
            for item in self._data:
                if "embedding" not in item:
                    continue
                item_vec = np.array(item["embedding"])
                similarity = np.dot(query_vec, item_vec) / (
                    np.linalg.norm(query_vec) * np.linalg.norm(item_vec) + 1e-8
                )
                results.append((similarity, item))

            results.sort(key=lambda x: x[0], reverse=True)
            return [item for _, item in results[:top_k]]
        except Exception as e:
            logger.warning(f"向量搜索失败: {e}")
            return []

    def get_all(self) -> list[dict]:
        """获取所有数据"""
        return self._data.copy()


def _memory_to_dict(memory: SemanticMemory) -> dict:
    """将 SemanticMemory 转换为字典"""
    return {
        "id": memory.id,
        "content": memory.content,
        "embedding": memory.embedding,
        "importance": memory.importance,
        "tags": memory.tags,
        "timestamp": memory.timestamp.isoformat(),
    }


class SemanticMemoryManager:
    """语义记忆管理器 - 支持自动降级，异步优化"""

    def __init__(self, config: MemoryConfig, character_id: str, base_path: Path):
        self.config = config
        self.character_id = character_id
        self._store = SimpleVectorStore(base_path / f"{character_id}_semantic.json")
        self._mode = SemanticMode.UNKNOWN  # 延迟检测
        self._mode_lock = asyncio.Lock()
        self._embedding_error_logged = False

        # 创建异步版本的 ollama 调用
        self._ollama_embeddings_async = sync_to_async(ollama.embeddings)
        self._ollama_chat_async = sync_to_async(ollama.chat)

    async def _ensure_mode_async(self) -> SemanticMode:
        """确保模式已检测（异步延迟检测）"""
        if self._mode != SemanticMode.UNKNOWN:
            return self._mode

        async with self._mode_lock:
            if self._mode != SemanticMode.UNKNOWN:
                return self._mode

            if not self.config.semantic_enabled:
                self._mode = SemanticMode.DISABLED
                return self._mode

            if await self._check_embedding_available_async():
                self._mode = SemanticMode.EMBEDDING
                logger.info(
                    f"语义记忆使用向量检索模式: {self.config.semantic_embedding_model}"
                )
            else:
                self._mode = SemanticMode.MODEL_EXTRACT
                logger.info("语义记忆降级为模型提取模式")

            return self._mode

    async def _check_embedding_available_async(self) -> bool:
        """检测 embedding 模型是否可用（异步）"""
        try:
            response = await self._ollama_embeddings_async(
                model=self.config.semantic_embedding_model, prompt="test"
            )
            return response is not None
        except Exception:
            return False

    async def _get_embedding_async(self, text: str) -> list[float] | None:
        """获取文本向量（异步）"""
        mode = await self._ensure_mode_async()
        if mode != SemanticMode.EMBEDDING:
            return None

        try:
            response = await self._ollama_embeddings_async(
                model=self.config.semantic_embedding_model, prompt=text
            )
            return response.embedding  # type: ignore
        except Exception as e:
            if not self._embedding_error_logged:
                logger.debug(f"Embedding 不可用，将使用模型提取模式: {e}")
                self._embedding_error_logged = True
            self._mode = SemanticMode.MODEL_EXTRACT
            return None

    async def _extract_key_info_with_model_async(
        self, content: str
    ) -> tuple[str, list[str]]:
        """使用模型提取关键信息（异步）"""
        prompt = f"""请从以下内容中提取关键信息，用于后续检索。
返回格式为 JSON，包含两个字段：
- summary: 一句话摘要（不超过50字）
- keywords: 关键词列表（3-5个）

内容：
{content}

只返回 JSON，不要其他内容。"""

        try:
            response = await self._ollama_chat_async(
                model=self.config.auto_memory_model,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                options={"temperature": 0.3},
            )

            result_text = response.message.content.strip()  # type: ignore

            import re

            json_match = re.search(r"\{.*\}", result_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return result.get("summary", content[:50]), result.get("keywords", [])
        except Exception as e:
            logger.debug(f"模型提取关键信息失败: {e}")

        return content[:50], []

    async def add_async(
        self, content: str, importance: float = 0.0, tags: list[str] | None = None
    ) -> str | None:
        """添加语义记忆（异步）"""
        mode = await self._ensure_mode_async()
        if mode == SemanticMode.DISABLED:
            return None

        memory = SemanticMemory(
            content=content, embedding=None, importance=importance, tags=tags or []
        )

        if mode == SemanticMode.EMBEDDING:
            embedding = await self._get_embedding_async(content)
            if embedding:
                memory.embedding = embedding

        memory_dict = _memory_to_dict(memory)

        if mode == SemanticMode.MODEL_EXTRACT or memory.embedding is None:
            summary, keywords = await self._extract_key_info_with_model_async(content)
            memory_dict["extracted_summary"] = summary
            memory_dict["extracted_keywords"] = keywords
            await self._store.add_async(memory_dict)
            logger.debug(f"异步添加语义记忆(模型提取): {summary[:30]}...")
        else:
            await self._store.add_async(memory_dict)
            logger.debug(f"异步添加语义记忆(向量): {content[:30]}...")

        return memory.id

    def _search_by_keywords(self, query: str, top_k: int) -> list[SemanticMemory]:
        """关键词匹配检索"""
        all_items = self._store.get_all()

        scored = []
        query_lower = query.lower()

        for item in all_items:
            score = 0
            content = item.get("content", "").lower()

            if query_lower in content:
                score += 5

            keywords = item.get("extracted_keywords", [])
            for kw in keywords:
                if kw.lower() in query_lower or query_lower in kw.lower():
                    score += 3

            summary = item.get("extracted_summary", "").lower()
            if query_lower in summary:
                score += 2

            if score > 0:
                scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)

        memories = []
        for _, item in scored[:top_k]:
            try:
                memories.append(
                    SemanticMemory(
                        id=item.get("id", ""),
                        content=item.get("content", ""),
                        embedding=item.get("embedding"),
                        importance=item.get("importance", 0.0),
                        tags=item.get("tags", []),
                    )
                )
            except Exception:
                pass

        return memories

    def get_relevant_context(self, query: str, top_k: int = 3) -> list[str]:
        """获取相关上下文（同步版本）"""
        if self._mode == SemanticMode.UNKNOWN:
            # 同步检测模式
            if self.config.semantic_enabled:
                try:
                    response = ollama.embeddings(
                        model=self.config.semantic_embedding_model, prompt="test"
                    )
                    self._mode = (
                        SemanticMode.EMBEDDING
                        if response
                        else SemanticMode.MODEL_EXTRACT
                    )
                except Exception:
                    self._mode = SemanticMode.MODEL_EXTRACT
            else:
                self._mode = SemanticMode.DISABLED

        if self._mode == SemanticMode.DISABLED:
            return []

        memories = self._search_by_keywords(query, top_k)
        return [m.content for m in memories if m.importance > 0.3]

    async def get_relevant_context_async(self, query: str, top_k: int = 3) -> list[str]:
        """获取相关上下文（异步）"""
        mode = await self._ensure_mode_async()
        if mode == SemanticMode.DISABLED:
            return []

        if mode == SemanticMode.EMBEDDING:
            embedding = await self._get_embedding_async(query)
            if embedding:
                results = self._store.search(embedding, top_k)
                memories = []
                for item in results:
                    try:
                        memories.append(
                            SemanticMemory(
                                id=item.get("id", ""),
                                content=item.get("content", ""),
                                embedding=item.get("embedding"),
                                importance=item.get("importance", 0.0),
                                tags=item.get("tags", []),
                            )
                        )
                    except Exception:
                        pass
                return [m.content for m in memories if m.importance > 0.3]

        memories = self._search_by_keywords(query, top_k)
        return [m.content for m in memories if m.importance > 0.3]
