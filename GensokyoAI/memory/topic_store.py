"""
话题感知的记忆存储 - 比阿求的记忆力还好DA☆ZE！

阿求：我编纂了《幻想乡缘起》，什么都记得！
本模块：我不光记得，还能联想，还会遗忘，还会情感标记！
帕秋莉：姆Q~ 这存储结构比我的图书馆还整齐...

Design Philosophy:
- 紫大人说：边界要模糊，所以话题之间要有重叠
- 幽幽子说：记忆太多会撑死的，所以要遗忘
- 魔理沙说：重要的东西要"借"久一点DA☆ZE~
"""

# GensokyoAI/memory/topic_store.py

import asyncio
import json
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import ayafileio
import msgspec

from ..core.agent.model_client import ModelClient
from ..core.config import TopicGenerationConfig
from ..utils.logger import logger
from .types import Topic, TopicMemory, TopicMemoryType


def _json_encoder(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _tokenize(text: str) -> set[str]:
    return {
        word
        for word in re.split(r"[\s,，。、；;！!？?·]+", text.lower())
        if 2 <= len(word) <= 20
    }


class TopicAwareStore:
    """
    话题感知存储 - 幻想乡最强记忆体

    能力：
    - 自主命名话题 (比琪露诺聪明多了)
    - 情感标记记忆 (比古明地觉还会读心)
    - 遗忘曲线 (比幽幽子吃得还慢)
    - 话题关联 (比紫的隙间还能连)
    """

    def __init__(
        self, path: Path, max_topics: int = 50, topic_config: TopicGenerationConfig | None = None
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
                if "last_accessed" in t_data and isinstance(t_data["last_accessed"], str):
                    t_data["last_accessed"] = datetime.fromisoformat(t_data["last_accessed"])

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

    def _rebuild_indexes(self) -> None:
        self._topic_name_index.clear()
        self._keyword_index.clear()
        for topic in self._topics.values():
            self._topic_name_index[topic.name.lower()] = topic.id
            self._index_topic(topic)

    # ==================== 遗忘曲线计算 ====================

    def _calculate_recall_weight(self, topic: Topic) -> float:
        """计算话题的回忆权重"""
        # 基础重要性
        base = topic.importance / max(topic.message_count, 1)

        # 古明地觉：你能感受到吗？
        emotional_factor = 1.0 + abs(topic.emotional_valence) * 2.0

        # 提取频率因子
        access_factor = 1.0 + min(topic.access_count / 10.0, 1.0)

        # 时间衰减
        days_since_access = (datetime.now() - topic.last_accessed).days
        half_life_days = 30 * emotional_factor * access_factor
        decay = 0.5 ** (days_since_access / half_life_days)

        return base * decay

    def _refresh_topic(self, topic: Topic, boost: float = 0.03) -> None:
        """刷新话题：更新时间戳，微量增加重要性"""
        topic.last_accessed = datetime.now()
        topic.access_count = getattr(topic, "access_count", 0) + 1
        topic.importance = min(topic.importance + boost, 10.0)

        logger.debug(f"话题 '{topic.name}' 被刷新，重要性: {topic.importance:.2f}")

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
            response = await model_client.chat(
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.1, "num_predict": 100},
            )

            result_text = response.message.content.strip()  # type: ignore
            json_match = re.search(r"\{[^}]+\}", result_text)

            if json_match:
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
        emotional_valence: float = 0.0,  # 🆕
        model_client: ModelClient | None = None,
        topic_name: str | None = None,
    ) -> Topic | None:
        """
        添加语义记忆！

        - 魔理沙：借来的记忆也要好好保存DA☆ZE！
        - 咲夜：比我的时停还快（异步嘛）
        """
        if not content:
            return None

        memory = TopicMemory(
            content=content,
            importance=importance,
            emotional_impact=abs(emotional_valence),  # 泪目了！
        )
        self._memories[memory.id] = memory

        if topic_name:
            topic_name_lower = topic_name.lower()

            if topic_name_lower in self._topic_name_index:
                topic_id = self._topic_name_index[topic_name_lower]
                topic = self._topics[topic_id]
                self._update_topic(topic, memory, importance, 10.0, emotional_valence)
                self._refresh_topic(topic, boost=0.05)
                await self._save_async()
                logger.debug(f"更新现有话题(由AI指定): {topic.name}")
                return topic

            topic = Topic(
                name=topic_name,
                summary=content[: self.topic_config.summary_max_length],
                importance=importance,
                emotional_valence=emotional_valence,  # 🆕
            )
            topic.message_ids.append(memory.id)
            topic.message_count = 1

            memory.topic_id = topic.id
            memory.tags = [topic_name]

            self._topics[topic.id] = topic
            self._topic_name_index[topic_name_lower] = topic.id
            self._index_topic(topic)

            await self._save_async()
            logger.info(
                f"创建新话题(由AI命名): 「{topic_name}」 (重要性: {importance:.2f}, 情感: {emotional_valence:.2f})"
            )
            return topic

        # 哎呀，话题名就是很难想嘛！
        candidates = self._get_candidates(content)

        if model_client and candidates:
            scores = await self._score_topics(content, candidates, model_client)

            if scores:
                best_id, best_score = max(scores.items(), key=lambda x: x[1])

                if best_score >= 7.0:
                    topic = self._topics[best_id]
                    self._update_topic(topic, memory, importance, best_score, emotional_valence)
                    self._refresh_topic(topic, boost=0.03)  # 🆕 刷新
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
            importance=importance,
            emotional_valence=emotional_valence,  # 🆕
        )
        topic.message_ids.append(memory.id)
        topic.message_count = 1

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
        emotional_valence: float = 0.0,
    ) -> None:
        """更新已有话题"""
        topic.last_updated = datetime.now()
        topic.message_count += 1
        topic.importance += importance * (score / 10.0)

        # 🆕 情感效价加权平均
        old_weight = topic.message_count - 1
        new_weight = 1
        topic.emotional_valence = (
            topic.emotional_valence * old_weight + emotional_valence * new_weight
        ) / topic.message_count

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

    def _keyword_memory_score(self, query: str, memory: TopicMemory, topic: Topic | None) -> tuple[float, list[str]]:
        query_tokens = _tokenize(query)
        memory_tokens = _tokenize(memory.content)
        topic_tokens = _tokenize(f"{topic.name} {topic.summary}" if topic else "")
        matched_memory = query_tokens & memory_tokens
        matched_topic = query_tokens & topic_tokens
        phrase_match = bool(query and query.lower() in memory.content.lower())

        score = 0.0
        if query_tokens:
            score += len(matched_memory) / len(query_tokens) * 0.55
            score += len(matched_topic) / len(query_tokens) * 0.25
        if phrase_match:
            score += 0.2
        score += min(memory.importance, 1.0) * 0.1
        if topic:
            score += min(self._calculate_recall_weight(topic), 1.0) * 0.1

        matched_by = []
        if matched_memory or phrase_match:
            matched_by.append("memory_keyword")
        if matched_topic:
            matched_by.append("topic_keyword")
        if not matched_by:
            matched_by.append("recent")
        return min(score, 1.0), matched_by

    @staticmethod
    def _cosine_similarity(left: list[float] | None, right: list[float] | None) -> float | None:
        if not left or not right or len(left) != len(right):
            return None
        dot = sum(a * b for a, b in zip(left, right, strict=False))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if left_norm == 0 or right_norm == 0:
            return None
        return dot / (left_norm * right_norm)

    def _memory_payload(
        self,
        memory: TopicMemory,
        *,
        topic: Topic | None = None,
        score: float | None = None,
        keyword_score: float | None = None,
        embedding_score: float | None = None,
        matched_by: list[str] | None = None,
        diagnostics: dict | None = None,
    ) -> dict:
        topic = topic or self._topics.get(memory.topic_id)
        payload = {
            "id": memory.id,
            "content": memory.content,
            "importance": memory.importance,
            "emotional_impact": memory.emotional_impact,
            "tags": list(memory.tags),
            "timestamp": memory.timestamp.isoformat(),
            "memory_type": memory.memory_type.name.lower(),
            "supersedes": memory.supersedes,
            "topic_id": memory.topic_id,
            "topic_name": topic.name if topic else None,
            "topic": self._topic_payload(topic) if topic else None,
            "embedding": None,
        }
        if score is not None:
            payload["score"] = score
        if keyword_score is not None:
            payload["keyword_score"] = keyword_score
        if embedding_score is not None:
            payload["embedding_score"] = embedding_score
        if matched_by is not None:
            payload["matched_by"] = matched_by
        if diagnostics is not None:
            payload["diagnostics"] = diagnostics
        return payload

    def _topic_payload(self, topic: Topic | None) -> dict | None:
        if topic is None:
            return None
        return {
            "id": topic.id,
            "name": topic.name,
            "summary": topic.summary,
            "created_at": topic.created_at.isoformat(),
            "last_updated": topic.last_updated.isoformat(),
            "last_accessed": topic.last_accessed.isoformat(),
            "access_count": topic.access_count,
            "message_count": topic.message_count,
            "importance": topic.importance,
            "emotional_valence": topic.emotional_valence,
            "recall_weight": self._calculate_recall_weight(topic),
            "related_topics": dict(topic.related_topics),
            "message_ids": list(topic.message_ids),
        }

    def search(
        self,
        top_k: int = 5,
        query_text: str | None = None,
        *,
        threshold: float = 0.0,
        query_embedding: list[float] | None = None,
        memory_embeddings: dict[str, list[float]] | None = None,
        embedding_weight: float = 0.55,
        refresh: bool = True,
        diagnostics: dict | None = None,
    ) -> list[dict]:
        """搜索记忆，按关键词/话题权重与可选 embedding 相似度排序。"""
        if not query_text or not self._memories:
            return []

        diagnostics = diagnostics or {}
        resolved_memory_embeddings = memory_embeddings or {}
        use_embedding = bool(query_embedding and resolved_memory_embeddings)
        keyword_weight = 1.0 - embedding_weight if use_embedding else 1.0
        candidates: list[dict] = []

        for memory in self._memories.values():
            topic = self._topics.get(memory.topic_id)
            keyword_score, matched_by = self._keyword_memory_score(query_text, memory, topic)
            embedding_score = None
            if use_embedding:
                embedding_score = self._cosine_similarity(
                    query_embedding,
                    resolved_memory_embeddings.get(memory.id),
                )
                if embedding_score is not None:
                    matched_by = [*matched_by, "embedding"]

            combined = keyword_score * keyword_weight
            if embedding_score is not None:
                combined += max(0.0, embedding_score) * embedding_weight
            if combined < threshold:
                continue

            candidates.append(
                self._memory_payload(
                    memory,
                    topic=topic,
                    score=combined,
                    keyword_score=keyword_score,
                    embedding_score=embedding_score,
                    matched_by=matched_by,
                    diagnostics=diagnostics,
                )
            )

        candidates.sort(
            key=lambda item: (
                item.get("score", 0.0),
                item.get("importance", 0.0),
                item.get("timestamp", ""),
            ),
            reverse=True,
        )

        for item in candidates[:top_k]:
            item_topic_id = item.get("topic_id")
            topic = self._topics.get(item_topic_id) if isinstance(item_topic_id, str) else None
            if topic and refresh:
                self._refresh_topic(topic, boost=0.01)

        return candidates[:top_k]

    def get_all(self) -> list[dict]:
        """获取所有记忆"""
        return [self._memory_payload(m) for m in self._memories.values()]

    def list_memories(
        self,
        *,
        topic_id: str | None = None,
        topic_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        topic = self.find_topic_by_name(topic_name) if topic_name else None
        selected_topic_id = topic_id or (topic.id if topic else None)
        memories = list(self._memories.values())
        if selected_topic_id:
            memories = [memory for memory in memories if memory.topic_id == selected_topic_id]
        memories.sort(key=lambda memory: memory.timestamp, reverse=True)
        total = len(memories)
        page = memories[max(offset, 0) : max(offset, 0) + max(limit, 1)]
        return {
            "items": [self._memory_payload(memory) for memory in page],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def list_topics(self) -> list[dict]:
        return [payload for topic in self._topics.values() if (payload := self._topic_payload(topic))]

    def get_memory(self, memory_id: str) -> dict | None:
        memory = self._memories.get(memory_id)
        return self._memory_payload(memory) if memory else None

    async def update_memory(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        importance: float | None = None,
        tags: list[str] | None = None,
    ) -> dict | None:
        memory = self._memories.get(memory_id)
        if memory is None:
            return None
        if content is not None:
            memory.content = content
        if importance is not None:
            memory.importance = max(0.0, min(1.0, float(importance)))
        if tags is not None:
            memory.tags = list(tags)
        await self._save_async()
        return self._memory_payload(memory)

    async def delete_memory(self, memory_id: str) -> bool:
        memory = self._memories.pop(memory_id, None)
        if memory is None:
            return False
        topic = self._topics.get(memory.topic_id)
        if topic and memory_id in topic.message_ids:
            topic.message_ids = [item for item in topic.message_ids if item != memory_id]
            topic.message_count = max(0, topic.message_count - 1)
            topic.last_updated = datetime.now()
            if topic.message_count == 0:
                self._topics.pop(topic.id, None)
        self._rebuild_indexes()
        await self._save_async()
        return True

    def get_all_topics(self) -> list[Topic]:
        """获取所有话题（只读）"""
        return list(self._topics.values())

    def find_topic_by_name(self, name: str | None) -> Topic | None:
        """根据话题名查找话题。"""
        if not name:
            return None
        topic_id = self._topic_name_index.get(name.lower())
        if not topic_id:
            return None
        return self._topics.get(topic_id)

    async def update_topic_memory(
        self,
        topic_name: str,
        content: str,
        *,
        importance: float = 0.7,
        score: float = 10.0,
        memory_type: TopicMemoryType = TopicMemoryType.CORRECTION,
    ) -> Topic | None:
        """为指定话题追加一条更新记忆，并返回更新后的话题。"""
        if not topic_name or not content:
            return None

        topic = self.find_topic_by_name(topic_name)
        if topic is None:
            return None

        memory = TopicMemory(
            content=content,
            importance=importance,
            memory_type=memory_type,
            supersedes=topic.message_ids[-1] if topic.message_ids else None,
        )
        self._memories[memory.id] = memory
        self._update_topic(topic, memory, importance, score)
        await self._save_async()
        return topic

    def get_topic_by_id(self, topic_id: str) -> Topic | None:
        """根据 ID 获取话题"""
        return self._topics.get(topic_id)

    def get_topic_graph(self) -> dict:
        """获取话题关联图"""
        nodes = [self._topic_payload(t) for t in self._topics.values()]

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
