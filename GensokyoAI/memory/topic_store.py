"""话题感知的记忆存储 - AI 自主命名话题"""

import re
import asyncio
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Optional

import msgspec
import ayafileio

from .types import Topic, TopicMemory
from ..utils.logging import logger
from ..core.config import TopicGenerationConfig
from ..core.agent.model_client import ModelClient


def _json_encoder(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


class TopicAwareStore:
    """话题感知存储 - AI 自主命名话题"""

    def __init__(
        self, path: Path, max_topics: int = 50, topic_config: Optional[TopicGenerationConfig] = None
    ):
        self.path = Path(path)
        self.max_topics = max_topics
        self.topic_config = topic_config or TopicGenerationConfig()

        self._topics: dict[str, Topic] = {}
        self._memories: dict[str, TopicMemory] = {}

        self._topic_name_index: dict[str, str] = {}
        self._keyword_index: dict[str, set[str]] = defaultdict(set)

        self._lock = asyncio.Lock()
        self._load_sync()

    # ==================== 持久化 ====================

    def _load_sync(self) -> None:
        """同步加载"""
        if not self.path.exists():
            return

        try:
            with open(self.path, "rb") as f:
                data = msgspec.json.decode(f.read())

            for t_data in data.get("topics", []):
                if "created_at" in t_data and isinstance(t_data["created_at"], str):
                    t_data["created_at"] = datetime.fromisoformat(t_data["created_at"])
                if "last_updated" in t_data and isinstance(t_data["last_updated"], str):
                    t_data["last_updated"] = datetime.fromisoformat(t_data["last_updated"])

                topic = Topic(name=t_data.pop("name", "未命名"), **t_data)
                self._topics[topic.id] = topic
                self._topic_name_index[topic.name.lower()] = topic.id
                self._index_topic(topic)

            for m_data in data.get("memories", []):
                if "timestamp" in m_data and isinstance(m_data["timestamp"], str):
                    m_data["timestamp"] = datetime.fromisoformat(m_data["timestamp"])
                memory = TopicMemory(content=m_data.pop("content", ""), **m_data)
                self._memories[memory.id] = memory

            logger.debug(f"加载话题存储: {len(self._topics)} 个话题, {len(self._memories)} 条记忆")

        except Exception as e:
            logger.warning(f"加载话题存储失败: {e}")

    async def _save_async(self) -> None:
        """异步保存"""
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "topics": list(self._topics.values()),
                "memories": list(self._memories.values()),
            }

            json_bytes = msgspec.json.format(
                msgspec.json.encode(data, enc_hook=_json_encoder), indent=2
            )

            async with ayafileio.open(self.path, "wb") as f:
                await f.write(json_bytes)

    def _index_topic(self, topic: Topic) -> None:
        """构建关键词索引"""
        text = f"{topic.name} {topic.summary}".lower()
        words = re.split(r"[\s,，。、；;！!？?·]+", text)

        for word in words:
            if 2 <= len(word) <= 20:
                self._keyword_index[word].add(topic.id)

    # ==================== 话题候选 ====================

    def _get_candidates(self, query: str, max_candidates: int = 5) -> list[Topic]:
        """获取候选话题"""
        if not self._topics:
            return []

        query_lower = query.lower()
        words = re.split(r"[\s,，。、；;！!？?·]+", query_lower)

        hits: dict[str, int] = defaultdict(int)
        for word in words:
            if 2 <= len(word) <= 20 and word in self._keyword_index:
                for tid in self._keyword_index[word]:
                    hits[tid] += 1

        candidates = []
        for tid, _ in sorted(hits.items(), key=lambda x: x[1], reverse=True):
            if tid in self._topics:
                candidates.append(self._topics[tid])
                if len(candidates) >= max_candidates:
                    break

        if len(candidates) < max_candidates:
            recent = sorted(self._topics.values(), key=lambda t: t.last_updated, reverse=True)
            for t in recent:
                if t not in candidates:
                    candidates.append(t)
                    if len(candidates) >= max_candidates:
                        break

        return candidates[:max_candidates]

    # ==================== LLM 评分 ====================

    async def _score_topics(
        self,
        content: str,
        candidates: list[Topic],
        model_client: ModelClient,
    ) -> dict[str, float]:
        """让 LLM 为候选话题打分"""
        if not candidates:
            return {}

        topics_desc = "\n".join(
            f"{i + 1}. 【{t.name}】{t.summary[:80]}" for i, t in enumerate(candidates)
        )

        prompt = f"""判断以下对话内容与各话题的相关性，给每个话题打 0-10 分。

内容：
{content}

话题列表：
{topics_desc}

只返回 JSON，格式：{{"1": 9, "2": 3}}"""

        try:
            response = await model_client.client.chat(
                model=model_client.model_name,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                options={"temperature": 0.1, "num_predict": 100},
            )

            result_text = response.message.content.strip()  # type: ignore
            json_match = re.search(r"\{[^}]+\}", result_text)

            if json_match:
                import json

                scores = json.loads(json_match.group())
                return {
                    candidates[i].id: float(scores.get(str(i + 1), 0))
                    for i in range(len(candidates))
                }

        except Exception as e:
            logger.debug(f"模型打分失败，使用降级方案: {e}")

        return self._fallback_score(content, candidates)

    def _fallback_score(self, content: str, candidates: list[Topic]) -> dict[str, float]:
        """降级方案：基于关键词匹配打分"""
        content_lower = content.lower()
        scores = {}

        for t in candidates:
            score = 0.0
            topic_text = f"{t.name} {t.summary}".lower()

            if t.name.lower() in content_lower:
                score += 5.0

            topic_words = set(re.split(r"[\s,，。、；;！!？?·]+", topic_text))
            content_words = set(re.split(r"[\s,，。、；;！!？?·]+", content_lower))
            common = topic_words & content_words
            score += len(common) * 0.5

            scores[t.id] = min(score, 10.0)

        return scores

    # ==================== 添加记忆 ====================

    async def add_async(
        self,
        content: str,
        importance: float = 0.0,
        model_client: Optional[ModelClient] = None,
        topic_name: Optional[str] = None,  # 🆕 AI 提供的话题名
    ) -> Optional[Topic]:
        """添加语义记忆"""
        if not content:
            return None

        memory = TopicMemory(
            content=content,
            importance=importance,
        )
        self._memories[memory.id] = memory

        # 🆕 优先使用 AI 提供的话题名
        if topic_name:
            topic_name_lower = topic_name.lower()

            # 检查是否已存在同名话题
            if topic_name_lower in self._topic_name_index:
                topic_id = self._topic_name_index[topic_name_lower]
                topic = self._topics[topic_id]
                self._update_topic(topic, memory, importance, 10.0)
                await self._save_async()
                logger.debug(f"更新现有话题(由AI指定): {topic.name}")
                return topic

            # 创建新话题，使用 AI 提供的名称
            topic = Topic(
                name=topic_name,
                summary=content[: self.topic_config.summary_max_length],
            )
            topic.message_ids.append(memory.id)
            topic.message_count = 1
            topic.importance = importance

            memory.topic_id = topic.id
            memory.tags = [topic_name]

            self._topics[topic.id] = topic
            self._topic_name_index[topic_name_lower] = topic.id
            self._index_topic(topic)

            await self._save_async()
            logger.info(f"创建新话题(由AI命名): 「{topic_name}」 (重要性: {importance:.2f})")
            return topic

        # 降级：AI 没有提供话题名，尝试匹配现有话题
        candidates = self._get_candidates(content)

        if model_client and candidates:
            scores = await self._score_topics(content, candidates, model_client)

            if scores:
                best_id, best_score = max(scores.items(), key=lambda x: x[1])

                if best_score >= 7.0:
                    topic = self._topics[best_id]
                    self._update_topic(topic, memory, importance, best_score)
                    self._update_edges(topic.id, scores)
                    await self._save_async()
                    logger.debug(f"更新话题: {topic.name} (相关性: {best_score:.1f})")
                    return topic

        # 最终降级：生成默认话题名
        fallback_name = f"话题{len(self._topics) + 1}"
        logger.info(f"使用降级话题名: {fallback_name}")

        topic = Topic(
            name=fallback_name,
            summary=content[: self.topic_config.summary_max_length],
        )
        topic.message_ids.append(memory.id)
        topic.message_count = 1
        topic.importance = importance

        memory.topic_id = topic.id
        memory.tags = [fallback_name]

        self._topics[topic.id] = topic
        self._topic_name_index[fallback_name.lower()] = topic.id
        self._index_topic(topic)

        await self._save_async()
        return topic

    def _update_topic(
        self,
        topic: Topic,
        memory: TopicMemory,
        importance: float,
        score: float,
    ) -> None:
        """更新已有话题"""
        topic.last_updated = datetime.now()
        topic.message_count += 1
        topic.importance += importance * (score / 10.0)
        topic.message_ids.append(memory.id)

        memory.topic_id = topic.id
        memory.tags = [topic.name]

    def _update_edges(self, topic_id: str, scores: dict[str, float]) -> None:
        """更新话题关联边"""
        topic = self._topics.get(topic_id)
        if not topic:
            return

        for other_id, score in scores.items():
            if other_id == topic_id or score < 4.0:
                continue

            old = topic.related_topics.get(other_id, score)
            topic.related_topics[other_id] = old * 0.7 + score * 0.3

            if other_id in self._topics:
                other = self._topics[other_id]
                old = other.related_topics.get(topic_id, score)
                other.related_topics[topic_id] = old * 0.7 + score * 0.3

    # ==================== 检索 ====================

    def search(
        self,
        top_k: int = 5,
        query_text: Optional[str] = None,
    ) -> list[dict]:
        """搜索记忆"""
        if not query_text or not self._topics:
            return []

        candidates = self._get_candidates(query_text, max_candidates=top_k)

        results = []
        for topic in candidates[:top_k]:
            memories = []
            for mid in topic.message_ids[-3:]:
                if mid in self._memories:
                    memories.append(self._memories[mid])

            results.append(
                {
                    "id": topic.id,
                    "content": topic.summary,
                    "importance": topic.importance / max(topic.message_count, 1),
                    "tags": [topic.name],
                    "extracted_summary": topic.summary,
                    "extracted_keywords": [topic.name],
                    "memories": [{"id": m.id, "content": m.content} for m in memories],
                }
            )

        return results

    def get_all(self) -> list[dict]:
        """获取所有记忆"""
        return [
            {
                "id": m.id,
                "content": m.content,
                "embedding": None,
                "importance": m.importance,
                "tags": m.tags,
                "timestamp": m.timestamp.isoformat(),
            }
            for m in self._memories.values()
        ]

    def get_topic_graph(self) -> dict:
        """获取话题关联图"""
        nodes = [
            {
                "id": t.id,
                "name": t.name,
                "summary": t.summary,
                "size": t.message_count,
                "importance": t.importance,
            }
            for t in self._topics.values()
        ]

        edges = []
        for t in self._topics.values():
            for rid, score in t.related_topics.items():
                if score >= 5.0 and rid in self._topics:
                    edges.append(
                        {
                            "source": t.id,
                            "target": rid,
                            "weight": score,
                        }
                    )

        return {"nodes": nodes, "edges": edges}

    def clear_cache(self) -> None:
        """清空关键词索引缓存"""
        self._keyword_index.clear()

    # ==================== 属性 ====================

    @property
    def topic_count(self) -> int:
        return len(self._topics)

    @property
    def memory_count(self) -> int:
        return len(self._memories)
