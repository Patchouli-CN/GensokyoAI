"""后台任务模块"""

#GenskoyoAI\background\__init__.py

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
from .workers import MemoryWorker, PersistenceWorker

__all__ = [
    "BackgroundManager",
    "BaseWorker",
    "BackgroundTask",
    "TaskResult",
    "TaskType",
    "TaskPriority",
    "MemoryTaskData",
    "PersistenceTaskData",
    "MemoryWorker",
    "PersistenceWorker",
]
