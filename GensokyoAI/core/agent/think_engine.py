"""静默思考引擎 - 模拟默认模式网络"""

# GensokyoAI/core/agent/think_engine.py

import asyncio
import random
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

from ...utils.logger import logger

if TYPE_CHECKING:
    from ...memory.semantic import SemanticMemoryManager
    from .model_client import ModelClient
    from ..events import EventBus
    from ..config import ThinkEngineConfig

# 为了研发这个引擎，下面是一个小故事：
# 上白泽慧音：
#  - **我思故我在，思想是一个人的重要组成部分！**
#  - **什么？你问我这个历史老师为什么说起哲学了？**
#  - **可能是阅历多了吧！**
class ThinkEngine:
    """
    静默思考引擎 - 让 AI 拥有自己的心理时间
    """

    def __init__(
        self,
        semantic_memory: "SemanticMemoryManager",
        model_client: "ModelClient",
        event_bus: "EventBus",
        character_name: str,
        config: "ThinkEngineConfig",  # 🆕 接收配置
    ):
        self.semantic_memory = semantic_memory
        self.model_client = model_client
        self.event_bus = event_bus
        self.character_name = character_name
        self.config = config

        self._running = False
        self._think_task: Optional[asyncio.Task] = None
        self._last_think_time: Optional[datetime] = None
        self._think_interval = timedelta(minutes=config.think_interval_minutes)

        # 待发送的主动消息队列
        self._pending_initiatives: list[str] = []

    async def start(self) -> None:
        """启动思考引擎"""
        if self._running or not self.config.enabled:
            return

        self._running = True
        self._think_task = asyncio.create_task(self._think_loop())
        logger.info(
            f"🧠 [{self.character_name}] 思考引擎已启动 (间隔: {self.config.think_interval_minutes}分钟)"
        )

    async def stop(self) -> None:
        """停止思考引擎"""
        self._running = False
        if self._think_task:
            self._think_task.cancel()
            try:
                await self._think_task
            except asyncio.CancelledError:
                pass
        logger.info(f"🧠 [{self.character_name}] 思考引擎已停止")

    async def _think_loop(self) -> None:
        """思考主循环"""
        while self._running:
            try:
                await asyncio.sleep(self._think_interval.total_seconds())

                if not self._running:
                    break

                await self._wander_and_think()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"思考循环异常: {e}")

    async def _wander_and_think(self) -> None:
        """随机游走话题图谱，产生联想"""
        store = self.semantic_memory.store
        topics = store.get_all_topics()

        if not topics:
            logger.debug(f"🧠 [{self.character_name}] 没有话题可思考")
            return

        # 优先选择高情感值的话题
        threshold = self.config.emotional_trigger_threshold
        emotional_topics = [t for t in topics if abs(t.emotional_valence) > threshold]

        if emotional_topics and random.random() < self.config.emotional_priority_probability:
            start_topic = random.choice(emotional_topics)
        else:
            start_topic = random.choice(topics)

        # 随机游走
        walk = [start_topic]
        current = start_topic
        steps = random.randint(self.config.random_walk_steps_min, self.config.random_walk_steps_max)

        for _ in range(steps):
            neighbors = list(current.related_topics.keys())
            if neighbors:
                # 按权重随机选择
                weights = [current.related_topics[n] for n in neighbors]
                current = store.get_topic_by_id(random.choices(neighbors, weights=weights)[0])
                if current:
                    walk.append(current)
                else:
                    break
            else:
                break

        # 构建思考提示
        walk_desc = "\n".join(
            f"- {t.name}: {t.summary} (情感: {t.emotional_valence:.2f})" for t in walk
        )

        prompt = f"""<think>
你现在处于静默状态，正在回顾与用户的过往。

你联想到了以下话题：
{walk_desc}

请在内心思考以下问题（不要输出给用户）：
1. 这些话题之间有什么联系？
2. 它们唤起了你怎样的情感？
3. 你是否有什么想主动对用户说的话或做的事？

只思考，不行动。记住你是{self.character_name}。
</think>"""

        logger.debug(f"🧠 [{self.character_name}] 正在静默思考，游走话题: {[t.name for t in walk]}")

        try:
            response = await self.model_client.client.chat(
                model=self.model_client.model_name,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                options={
                    "temperature": self.config.think_temperature,
                    "num_predict": self.config.think_max_tokens,
                },
            )

            thought = response.message.content
            if thought:
                logger.info(f"💭 [{self.character_name}] 内心独白: {thought[:100]}...")

                # 检查是否产生主动意图
                if self._has_initiative_intent(thought):
                    initiative = await self._generate_initiative(thought, walk)
                    if initiative:
                        self._pending_initiatives.append(initiative)
                        logger.info(
                            f"✨ [{self.character_name}] 产生主动意图: {initiative[:50]}..."
                        )

        except Exception as e:
            logger.error(f"静默思考失败: {e}")

    def _has_initiative_intent(self, thought: str) -> bool:
        """判断是否产生主动意图"""
        thought_lower = thought.lower()
        return any(kw in thought_lower for kw in self.config.initiative_detection_keywords)

    async def _generate_initiative(self, thought: str, walk: list) -> Optional[str]:
        """根据思考生成主动消息"""
        topics_desc = "\n".join(f"- {t.name}: {t.summary}" for t in walk[:3])

        prompt = f"""基于你的静默思考，你决定主动对用户说些什么。

相关话题：
{topics_desc}

你的思考：
{thought}

请生成一句你想主动对用户说的话（保持角色风格，自然、不生硬）。
只输出这句话，不要任何额外内容。"""

        try:
            response = await self.model_client.client.chat(
                model=self.model_client.model_name,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                options={
                    "temperature": self.config.initiative_temperature,
                    "num_predict": self.config.initiative_max_tokens,
                },
            )

            return response.message.content.strip() if response.message.content else None

        except Exception as e:
            logger.error(f"生成主动消息失败: {e}")
            return None

    def get_pending_initiative(self) -> Optional[str]:
        """获取并清空待发送的主动消息"""
        if self._pending_initiatives:
            return self._pending_initiatives.pop(0)
        return None

    def has_pending_initiative(self) -> bool:
        """是否有待发送的主动消息"""
        return len(self._pending_initiatives) > 0

    def trigger_think_now(self) -> None:
        """立即触发一次思考"""
        if self._running:
            asyncio.create_task(self._wander_and_think())
