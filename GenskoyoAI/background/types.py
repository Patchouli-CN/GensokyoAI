"""后台任务数据类型"""

#GenskoyoAI\background\types.py

from msgspec import Struct, field
from datetime import datetime
from enum import Enum, auto
from typing import Any
from uuid import uuid4


class TaskPriority(Enum):
    """任务优先级"""

    LOW = auto()
    NORMAL = auto()
    HIGH = auto()
    CRITICAL = auto()


class TaskType(Enum):
    """任务类型"""

    MEMORY = auto()  # 记忆处理
    PERSISTENCE = auto()  # 持久化
    EVENT = auto()  # 事件处理
    CUSTOM = auto()  # 自定义


class BackgroundTask(Struct, frozen=False):
    """后台任务"""

    id: str = field(default_factory=lambda: str(uuid4()))
    type: TaskType = TaskType.CUSTOM
    priority: TaskPriority = TaskPriority.NORMAL
    name: str = ""
    data: Any = None
    created_at: datetime = field(default_factory=datetime.now)
    timeout: float = 30.0  # 超时时间（秒）
    retry_count: int = 0
    max_retries: int = 1


class TaskResult(Struct):
    """任务执行结果"""

    task_id: str
    success: bool
    result: Any = None
    error: str | None = None
    duration_ms: float = 0.0


class MemoryTaskData(Struct):
    """记忆任务数据"""

    user_input: str
    assistant_response: str
    session_id: str | None = None


class PersistenceTaskData(Struct):
    """持久化任务数据"""

    operation: str  # "save_session", "save_messages", "save_vector_store"
    data: Any
    path: str | None = None


class EventTaskData(Struct):
    """事件任务数据"""

    event_name: str
    event_data: Any = None
    source: str | None = None
