"""记忆数据类"""

# GensokyoAI\memory\types.py

from msgspec import Struct, field
from datetime import datetime
from uuid import uuid4


class MemoryRecord(Struct):
    """基础记忆记录"""

    id: str = field(default_factory=lambda: str(uuid4()))
    content: str = ""
    role: str = "user"  # user/assistant/system/tool
    timestamp: datetime = field(default_factory=datetime.now)
    character_id: str = "default"
    importance: float = 0.0  # 0-1 重要程度
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
            self.messages = self.messages[-self.max_turns * 2:]

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


class Topic(Struct):
    """话题 - 对话的语义聚类单元
    注意：无默认值的字段必须放在有默认值的字段之前
    """

    name: str  # 无默认值，放最前
    id: str = field(default_factory=lambda: str(uuid4())[:8])
    summary: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)
    message_count: int = 0
    importance: float = 0.0
    related_topics: dict[str, float] = field(default_factory=dict)
    message_ids: list[str] = field(default_factory=list)


class TopicMemory(Struct):
    """话题记忆 - 用于话题检索
    注意：无默认值的字段必须放在有默认值的字段之前
    """

    content: str  # 无默认值，放最前
    id: str = field(default_factory=lambda: str(uuid4())[:8])
    topic_id: str = ""
    importance: float = 0.0
    tags: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)