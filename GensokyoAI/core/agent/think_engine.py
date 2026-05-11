"""静默思考引擎 - 模拟默认模式网络"""

# GensokyoAI/core/agent/think_engine.py

import asyncio
import contextlib
import random
from datetime import datetime, timedelta

from ...memory.semantic import SemanticMemoryManager
from ...utils.logger import logger
from ..config import ThinkEngineConfig
from ..events import Event, EventBus, SystemEvent
from .model_client import ModelClient


# 为了研发这个引擎，下面是一个小故事：
# 上白泽慧音：
#  - **我思故我在，思想是一个人的重要组成部分！**
#  - **什么？你问我这个历史老师为什么说起哲学了？**
#  - **可能是阅历多了吧！**
class ThinkEngine:
    """
    静默思考引擎 - 让 AI 拥有自己的心理时间

    职责：
    - 定时触发思考
    - 随机游走话题图谱，产生联想
    - 调用 LLM 进行静默思考
    - 发布思考结果事件（THINK_ENGINE_THOUGHT）
    - ❌ 不负责决策（交给 ActionPlanner）
    - ❌ 不负责生成主动消息（交给 ActionPlanner）
    """

    def __init__(
        self,
        semantic_memory: SemanticMemoryManager,
        model_client: ModelClient,
        event_bus: EventBus,
        character_name: str,
        config: ThinkEngineConfig,
        debug_silent_output: bool = False,
    ):
        self.semantic_memory = semantic_memory
        self.model_client = model_client
        self.event_bus = event_bus
        self.character_name = character_name
        self.config = config
        self.debug_silent_output = debug_silent_output

        self._running = False
        self._think_task: asyncio.Task | None = None
        self._last_think_time: datetime | None = None
        self._think_interval = timedelta(minutes=config.think_interval_minutes)

    async def start(self) -> None:
        """启动思考引擎"""
        if self._running or not self.config.enabled:
            return

        self._running = True
        self._think_task = asyncio.create_task(self._think_loop())
        logger.info(
            f"🧠 [ThinkEngine] 思考引擎已启动 (角色: {self.character_name}, 间隔: {self.config.think_interval_minutes}分钟)"
        )

    async def stop(self) -> None:
        """停止思考引擎"""
        self._running = False
        if self._think_task:
            self._think_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._think_task
        logger.info(f"🧠 [ThinkEngine] 思考引擎已停止 (角色: {self.character_name})")

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
            logger.debug(f"🧠 [ThinkEngine] {self.character_name} 没有话题可思考")
            return

        # 优先选择高情感值的话题
        threshold = self.config.emotional_trigger_threshold
        emotional_topics = [t for t in topics if abs(t.emotional_valence) > threshold]

        if emotional_topics and random.random() < self.config.emotional_priority_probability:
            start_topic = random.choice(emotional_topics)
            logger.debug(
                f"🧠 [ThinkEngine] {self.character_name} 优先选择高情感话题: {start_topic.name}"
            )
        else:
            start_topic = random.choice(topics)

        # 随机游走
        walk = [start_topic]
        current = start_topic
        steps = random.randint(self.config.random_walk_steps_min, self.config.random_walk_steps_max)

        for _ in range(steps):
            neighbors = list(current.related_topics.keys())
            if neighbors:
                weights = [current.related_topics[n] for n in neighbors]
                next_id = random.choices(neighbors, weights=weights)[0]
                current = store.get_topic_by_id(next_id)
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

        prompt = f"""
你现在处于静默状态，正在回顾与用户的过往。

你联想到了以下话题：
{walk_desc}

请在内心思考以下问题（不要输出给用户）：
1. 这些话题之间有什么联系？
2. 它们唤起了你怎样的情感？
3. 你是否有什么想主动对用户说的话或做的事？

只思考，不行动。记住你是{self.character_name}。
"""

        logger.debug(
            f"🧠 [ThinkEngine] {self.character_name} 正在静默思考，游走话题: {[t.name for t in walk]}"
        )

        try:
            response = await self.model_client.chat(
                messages=[{"role": "system", "content": prompt}],
                options={
                    "temperature": self.config.think_temperature,
                    "num_predict": self.config.think_max_tokens,
                },
            )

            thought = response.message.content
            if thought:
                if self.debug_silent_output:
                    logger.info(
                        f"💭 [ThinkEngine] {self.character_name} 内心独白: {thought[:100]}..."
                    )
                else:
                    logger.debug(
                        f"💭 [ThinkEngine] {self.character_name} 产生静默思考（调试输出关闭，内容已隐藏）"
                    )

                # 🆕 只发布思考事件，不判断意图，不生成消息
                # 决策交给 ActionPlanner
                self.event_bus.publish(
                    Event(
                        type=SystemEvent.THINK_ENGINE_THOUGHT,
                        source="think_engine",
                        data={
                            "character": self.character_name,
                            "thought": thought,
                            "topics": [t.name for t in walk],
                            "topics_detail": [
                                {
                                    "name": t.name,
                                    "summary": t.summary,
                                    "emotional_valence": t.emotional_valence,
                                }
                                for t in walk[:3]
                            ],
                        },
                    )
                )
            else:
                logger.debug(f"🤫 [ThinkEngine] {self.character_name} 思考了但内容为空")

        except Exception as e:
            logger.error(f"静默思考失败: {e}")

    def trigger_think_now(self) -> None:
        """立即触发一次思考"""
        if self._running:
            asyncio.create_task(self._wander_and_think())
            logger.debug(f"🧠 [ThinkEngine] {self.character_name} 手动触发思考")
