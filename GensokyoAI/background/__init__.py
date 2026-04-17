"""后台任务模块"""

# GensokyoAI\background\__init__.py

from .manager import BackgroundManager
from .workers.base import BaseWorker
from .types import (
    BackgroundTask,
    TaskResult,
    TaskType,
    TaskPriority,
    MemoryTaskData,
    PersistenceTaskData,
)
from .workers import PersistenceWorker

__all__ = [
    "BackgroundManager",
    "BaseWorker",
    "BackgroundTask",
    "TaskResult",
    "TaskType",
    "TaskPriority",
    "MemoryTaskData",
    "PersistenceTaskData",
    "PersistenceWorker",
]
