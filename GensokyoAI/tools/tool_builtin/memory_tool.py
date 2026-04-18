# GensokyoAI/tools/tool_builtin/memory_tool.py

"""记忆工具 - 通过事件总线操作记忆（异步非阻塞）"""

from typing import Optional, TYPE_CHECKING

from ..base import tool
from ...utils.logging import logger
from ...core.events import Event, SystemEvent

if TYPE_CHECKING:
    from ...core.events import EventBus


_event_bus: Optional["EventBus"] = None


def set_event_bus(event_bus: "EventBus") -> None:
    """注入事件总线"""
    global _event_bus
    _event_bus = event_bus


def get_event_bus() -> Optional["EventBus"]:
    """获取事件总线"""
    return _event_bus


@tool()
async def remember(
    content: str,
    topic: str = "",
    importance: int = 5,
    emotional_valence: float = 0.0,  # 🆕 情感效价 -1.0到1.0
) -> str:
    """
    记住重要的信息。当你了解到新的事实、产生情感波动或发现重要事件时主动调用。

    Args:
        content: 要记住的内容
        topic: 话题名称，用于归类记忆。如果不填，系统会自动匹配
        importance: 重要性 1-10
        emotional_valence: 情感效价，-1.0(极度负面) 到 1.0(极度正面)，0为中性
    """
    event_bus = get_event_bus()
    if event_bus is None:
        logger.warning("事件总线未初始化")
        return "「唔…记忆功能好像还没准备好…」"

    if not content or len(content) <= 1:
        return "「这个…好像没什么值得记的…」"

    importance = max(1, min(10, importance))
    normalized_importance = importance / 10.0

    # 限制情感范围
    emotional_valence = max(-1.0, min(1.0, emotional_valence))

    request_event = Event(
        type=SystemEvent.MEMORY_SEMANTIC_ADDED,
        source="tool.remember",
        data={
            "content": content,
            "importance": normalized_importance,
            "emotional_valence": emotional_valence,  # 🆕
            "topic_name": topic if topic else None,
        },
    )

    result = await event_bus.request(request_event, timeout=10.0)

    if result and isinstance(result, dict):
        topic_name = result.get("topic_name", topic or "记忆")
        if importance >= 8:
            if abs(emotional_valence) > 0.7:
                return f"「这件事让我感触很深，我会永远记住的！({topic_name})」"
            return f"「这个很重要，我记住了！({topic_name})」"
        else:
            return f"「嗯，记住了～」"

    return "「记住了～」"


@tool()
async def recall(
    keyword: str,
    page: int = 1,
) -> str:
    """
    回忆之前记住的信息。当你需要引用已知事实、回忆过往情感或查找历史事件时调用。

    Args:
        keyword: 搜索关键词
        page: 页码，从1开始
    """
    event_bus = get_event_bus()
    if event_bus is None:
        return "「记忆功能还没准备好…」"

    if not keyword:
        return "「你想让我回忆什么？」"

    request_event = Event(
        type=SystemEvent.MEMORY_SEMANTIC_RECALLED,
        source="tool.recall",
        data={
            "keyword": keyword,
            "page": page,
        },
    )

    result = await event_bus.request(request_event, timeout=10.0)

    if result and isinstance(result, str):
        return result

    return f"「关于 '{keyword}' …我好像没什么印象…」"


@tool()
async def update_memory(
    topic: str,
    new_content: str,
    reason: str = "信息更新",
) -> str:
    """
    🆕 更新已有的记忆（当发现旧信息过时或不准确时调用）

    Args:
        topic: 要更新的话题名
        new_content: 新的记忆内容
        reason: 更新原因
    """
    event_bus = get_event_bus()
    if event_bus is None:
        return "「记忆功能还没准备好…」"

    request_event = Event(
        type=SystemEvent.MEMORY_SEMANTIC_UPDATED,
        source="tool.update_memory",
        data={
            "topic_name": topic,
            "new_content": new_content,
            "reason": reason,
        },
    )

    result = await event_bus.request(request_event, timeout=10.0)

    if result:
        return f"「嗯，我更新了关于'{topic}'的记忆。{reason}」"

    return f"「关于'{topic}'的记忆更新失败了…」"
