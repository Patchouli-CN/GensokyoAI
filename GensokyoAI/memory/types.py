# GensokyoAI/memory/types.py

"""记忆数据类"""

from enum import Enum, auto
from msgspec import Struct, field
from datetime import datetime
from uuid import uuid4
from typing import Optional


class TopicMemoryType(Enum):
    FACT = auto()
    PREFERENCE = auto()
    EVENT = auto()
    CORRECTION = auto()


class MemoryRecord(Struct):
    """基础记忆记录"""

    id: str = field(default_factory=lambda: str(uuid4()))
    content: str = ""
    role: str = "user"  # user/assistant/system/tool
    timestamp: datetime = field(default_factory=datetime.now)
    character_id: str = "default"
    importance: float = 0.0  # 0-1 重要程度
    emotional_valence: float = 0.0  # 🆕 情感效价 -1.0 到 1.0
    metadata: dict = field(default_factory=dict)


class WorkingMemory(Struct):
    """工作记忆 - 当前会话的完整对话"""

    messages: list[dict] = field(default_factory=list)
    max_turns: int = 20

    def add(self, role: str, content: str, **kwargs) -> None:
        """添加消息"""
        self.messages.append({"role": role, "content": content, **kwargs})
        self._trim()

    def _trim(self) -> None:
        """裁剪到最大轮数"""
        if len(self.messages) > self.max_turns * 2:
            self.messages = self.messages[-self.max_turns * 2 :]

    def get_context(self) -> list[dict]:
        """获取上下文"""
        return self.messages.copy()

    def clear(self) -> None:
        """清空"""
        self.messages.clear()


class EpisodicMemory(Struct):
    """情景记忆 - 历史摘要"""

    summary: str = ""
    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime | None = None
    message_count: int = 0
    key_events: list[str] = field(default_factory=list)
    emotional_valence: float = 0.0  # 🆕 情感效价
    location: str = ""  # 🆕 地点


class Topic(Struct):
    """话题 - 对话的语义聚类单元"""

    name: str  # 无默认值，放最前
    id: str = field(default_factory=lambda: str(uuid4())[:8])
    summary: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)
    last_accessed: datetime = field(default_factory=datetime.now)  # 🆕 最后访问时间
    access_count: int = 0  # 🆕 访问次数
    message_count: int = 0
    importance: float = 0.0
    emotional_valence: float = 0.0  # 🆕 情感效价
    related_topics: dict[str, float] = field(default_factory=dict)
    message_ids: list[str] = field(default_factory=list)


class TopicMemory(Struct):
    """话题记忆 - 用于话题检索"""

    content: str  # 无默认值，放最前
    id: str = field(default_factory=lambda: str(uuid4())[:8])
    topic_id: str = ""
    importance: float = 0.0
    emotional_impact: float = 0.0  # 🆕 情感冲击力
    tags: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    memory_type: TopicMemoryType = TopicMemoryType.FACT
    supersedes: Optional[str] = None
