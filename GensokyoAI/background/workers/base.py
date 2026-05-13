"""工作器基类"""
# GensokyoAI\background\workers\base.py

from abc import ABC, abstractmethod

from ..types import BackgroundTask, TaskResult


class BaseWorker(ABC):
    """工作器基类"""

    @abstractmethod
    async def process(self, task: BackgroundTask) -> TaskResult:
        """处理任务并返回任务结果。"""
        raise NotImplementedError
