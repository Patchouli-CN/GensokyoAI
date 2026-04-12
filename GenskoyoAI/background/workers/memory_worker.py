"""记忆处理工作器"""

# GenskoyoAI\background\workers\memory_worker.py

import asyncio
import time
from typing import TYPE_CHECKING

from ...utils.logging import logger
from .base import BaseWorker
from ..types import BackgroundTask, TaskResult, MemoryTaskData

if TYPE_CHECKING:
    from ...memory.semantic import SemanticMemoryManager
    from ...core.config import MemoryConfig


class MemoryWorker(BaseWorker):
    """记忆处理工作器 - 负责异步处理语义记忆"""

    def __init__(
        self,
        semantic_memory: "SemanticMemoryManager",
        config: "MemoryConfig",
    ):
        self.semantic_memory = semantic_memory
        self.config = config
        self._embedding_cache: dict[str, list[float]] = {}
        self._cache_max_size = 50
        # 添加错误计数和降级标记
        self._consecutive_failures = 0
        self._max_failures_before_downgrade = 3
        self._downgraded = False

    async def process(self, task: BackgroundTask) -> TaskResult:
        """处理记忆任务 - 优化版"""
        start_time = time.time()

        try:
            if not isinstance(task.data, MemoryTaskData):
                raise ValueError(f"Invalid task data type: {type(task.data)}")

            data: MemoryTaskData = task.data

            # 如果已经降级，跳过重要性计算，直接处理
            if self._downgraded:
                importance = 0.3  # 默认较低重要性
            else:
                importance = self._calculate_importance(
                    data.user_input, data.assistant_response
                )

            if importance > 0.5 or self._downgraded:
                try:
                    await asyncio.wait_for(
                        self.semantic_memory.add_async(data.user_input, importance),
                        timeout=task.timeout,
                    )
                    self._consecutive_failures = 0  # 成功时重置计数
                    logger.debug(f"✓ 记忆已保存 (重要性: {importance:.2f})")
                except Exception as e:
                    self._consecutive_failures += 1
                    if (
                        self._consecutive_failures
                        >= self._max_failures_before_downgrade
                    ):
                        self._downgraded = True
                        logger.warning(
                            f"记忆处理连续失败 {self._consecutive_failures} 次，已降级处理"
                        )
                    raise

            duration_ms = (time.time() - start_time) * 1000

            return TaskResult(
                task_id=task.id,
                success=True,
                result={"importance": importance, "downgraded": self._downgraded},
                duration_ms=duration_ms,
            )

        except asyncio.TimeoutError:
            self._consecutive_failures += 1
            duration_ms = (time.time() - start_time) * 1000
            logger.debug(f"⏱️ 记忆处理超时 ({task.timeout}s)")
            return TaskResult(
                task_id=task.id,
                success=False,
                error="timeout",
                duration_ms=duration_ms,
            )
        except Exception as e:
            self._consecutive_failures += 1
            duration_ms = (time.time() - start_time) * 1000
            logger.debug(f"❌ 记忆处理失败: {e}")
            return TaskResult(
                task_id=task.id,
                success=False,
                error=str(e),
                duration_ms=duration_ms,
            )

    def _calculate_importance(self, user_input: str, assistant_response: str) -> float:
        """计算对话重要性"""
        importance = 0.0

        if len(user_input) > 50:
            importance += 0.3
        if any(kw in user_input for kw in ["记住", "重要", "我叫", "我是", "设定"]):
            importance += 0.4
        if len(assistant_response) > 100:
            importance += 0.2
        if any(kw in user_input for kw in ["忘记", "不重要", "临时"]):
            importance -= 0.3

        return min(max(importance, 0.0), 1.0)

    def clear_cache(self) -> None:
        """清空 embedding 缓存"""
        self._embedding_cache.clear()

    def reset_downgrade(self) -> None:
        """重置降级状态"""
        self._consecutive_failures = 0
        self._downgraded = False
        logger.info("记忆工作器降级状态已重置")

    @property
    def is_downgraded(self) -> bool:
        """是否处于降级状态"""
        return self._downgraded
