"""后台任务模块"""

# GensokyoAI\background\__init__.py

from .manager import BackgroundManager
from .types import (
    BackgroundTask,
    PersistenceTaskData,
    TaskPriority,
    TaskResult,
    TaskType,
)
from .workers import PersistenceWorker
from .workers.base import BaseWorker

__all__ = [
    "BackgroundManager",
    "BaseWorker",
    "BackgroundTask",
    "TaskResult",
    "TaskType",
    "TaskPriority",
    "PersistenceTaskData",
    "PersistenceWorker",
]
