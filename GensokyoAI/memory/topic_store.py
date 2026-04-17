"""话题感知的记忆存储 - 让模型自己判断话题相关性"""

import re
import json
import asyncio
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Optional, TYPE_CHECKING

import ayafileio

from .types import Topic, TopicMemory
from ..utils.logging import logger

if TYPE_CHECKING:
    from ..core.agent.model_client import ModelClient


class TopicAwareStore:
    """话题感知存储"""

    def __init__(self, path: Path, max_topics: int = 50):
        self.path = Path(path)
        self.max_topics = max_topics

        self._topics: dict[str, Topic] = {}
        self._memories: dict[str, TopicMemory] = {}

        self._topic_name_index: dict[str, str] = {}
        self._keyword_index: dict[str, set[str]] = defaultdict(set)

        self._lock = asyncio.Lock()
        self._load_sync()

    # ==================== 持久化 ====================

    def _load_sync(self) -> None:
        if not self.path.exists():
            return

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for t_data in data.get("topics", []):
                if "created_at" in t_data:
                    t_data["created_at"] = datetime.fromisoformat(t_data["created_at"])
                if "last_updated" in t_data:
                    t_data["last_updated"] = datetime.fromisoformat(t_data["last_updated"])

                # 使用关键字参数创建，确保 name 在前面
                topic = Topic(
                    name=t_data.pop("name", "未命名"),
                    **t_data
                )
                self._topics[topic.id] = topic
                self._topic_name_index[topic.name.lower()] = topic.id
                self._index_topic(topic)

            for m_data in data.get("memories", []):
                if "timestamp" in m_data:
                    m_data["timestamp"] = datetime.fromisoformat(m_data["timestamp"])
                memory = TopicMemory(
                    content=m_data.pop("content", ""),
                    **m_data
                )
                self._memories[memory.id] = memory

            logger.debug(f"加载话题存储: {len(self._topics)} 个话题, {len(self._memories)} 条记忆")

        except Exception as e:
            logger.warning(f"加载话题存储失败: {e}")

    async def _save_async(self) -> None:
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)

            def to_dict(obj):
                if isinstance(obj, datetime):
                    return obj.isoformat()
                if hasattr(obj, "__dict__"):
                    return {k: to_dict(v) for k, v in obj.__dict__.items() if not k.startswith("_")}
                return obj

            data = {
                "topics": [to_dict(t) for t in self._topics.values()],
                "memories": [to_dict(m) for m in self._memories.values()],
            }

            async with ayafileio.open(self.path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(data, ensure_ascii=False, indent=2))

    def _index_topic(self, topic: Topic) -> None:
        text = f"{topic.name} {topic.summary}".lower()
        words = re.split(r"[\s,，。、；;！!？?·]+", text)

        for word in words:
            if 2 <= len(word) <= 20:
                self._keyword_index[word].add(topic.id)

    def _get_candidates(self, query: str, max_candidates: int = 5) -> list[Topic]:
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

    async def _score_topics(
        self,
        content: str,
        candidates: list[Topic],
        model_client: "ModelClient",
    ) -> dict[str, float]:
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
                scores = json.loads(json_match.group())
                return {
                    candidates[i].id: float(scores.get(str(i + 1), 0))
                    for i in range(len(candidates))
                }

        except Exception as e:
            logger.debug(f"模型打分失败，使用降级方案: {e}")

        return self._fallback_score(content, candidates)

    def _fallback_score(self, content: str, candidates: list[Topic]) -> dict[str, float]:
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

    async def _generate_topic_info(
        self,
        content: str,
        model_client: "ModelClient",
    ) -> tuple[str, str]:
        prompt = f"""为以下对话生成话题名（≤10字）和摘要（≤50字）。

内容：
{content}

只返回 JSON：{{"name": "话题名", "summary": "摘要"}}"""

        try:
            response = await model_client.client.chat(
                model=model_client.model_name,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                options={"temperature": 0.3, "num_predict": 100},
            )

            result_text = response.message.content.strip()  # type: ignore
            json_match = re.search(r"\{[^}]+\}", result_text)

            if json_match:
                data = json.loads(json_match.group())
                return data.get("name", "未命名"), data.get("summary", content[:50])

        except Exception as e:
            logger.debug(f"生成话题信息失败: {e}")

        return f"话题{len(self._topics) + 1}", content[:50]

    async def add_async(
        self,
        content: str,
        importance: float = 0.0,
        model_client: Optional["ModelClient"] = None,
    ) -> Optional[Topic]:
        if not content:
            return None

        candidates = self._get_candidates(content)

        memory = TopicMemory(
            content=content,
            importance=importance,
        )
        self._memories[memory.id] = memory

        if model_client and candidates:
            scores = await self._score_topics(content, candidates, model_client)

            if scores:
                best_id, best_score = max(scores.items(), key=lambda x: x[1])

                if best_score >= 7.0:
                    topic = self._topics[best_id]
                    self._update_topic(topic, memory, importance, best_score)
                    self._update_edges(topic.id, scores)
                    await self._save_async()
                    return topic

        if model_client:
            name, summary = await self._generate_topic_info(content, model_client)
        else:
            name = f"话题{len(self._topics) + 1}"
            summary = content[:50]

        topic = Topic(
            name=name,
            summary=summary,
        )
        topic.message_ids.append(memory.id)
        topic.message_count = 1
        topic.importance = importance

        memory.topic_id = topic.id
        memory.tags = [name]

        self._topics[topic.id] = topic
        self._topic_name_index[name.lower()] = topic.id
        self._index_topic(topic)

        if candidates and model_client:
            scores = await self._score_topics(content, candidates, model_client)
            for cand_id, score in scores.items():
                if score >= 4.0:
                    topic.related_topics[cand_id] = score

        await self._save_async()
        logger.debug(f"创建新话题: {name} (重要性: {importance:.2f})")
        return topic

    def _update_topic(
        self,
        topic: Topic,
        memory: TopicMemory,
        importance: float,
        score: float,
    ) -> None:
        topic.last_updated = datetime.now()
        topic.message_count += 1
        topic.importance += importance * (score / 10.0)
        topic.message_ids.append(memory.id)

        memory.topic_id = topic.id
        memory.tags = [topic.name]

    def _update_edges(self, topic_id: str, scores: dict[str, float]) -> None:
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

    def search(
        self,
        top_k: int = 5,
        query_text: Optional[str] = None,
    ) -> list[dict]:
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
        self._keyword_index.clear()

    @property
    def topic_count(self) -> int:
        return len(self._topics)

    @property
    def memory_count(self) -> int:
        return len(self._memories)