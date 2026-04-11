"""工作器基类"""

from abc import ABC, abstractmethod
from ..types import BackgroundTask, TaskResult


class BaseWorker(ABC):
    """工作器基类"""

    @abstractmethod
    async def process(self, task: BackgroundTask) -> TaskResult:
        """处理任务"""
        pass
