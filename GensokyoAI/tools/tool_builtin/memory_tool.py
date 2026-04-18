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
    topic: str = "",  # 🆕 让 AI 自己指定话题名
    category: str = "general",
    importance: int = 5,
) -> str:
    """
    记住重要的信息。当你了解到新的事实时主动调用。

    Args:
        content: 要记住的内容
        topic: 话题名称，用于归类记忆。如果不填，系统会自动生成
        category: 分类 - character, event, location, preference, knowledge, general
        importance: 重要性 1-10
    """
    event_bus = get_event_bus()
    if event_bus is None:
        logger.warning("事件总线未初始化")
        return "「唔…记忆功能好像还没准备好…」"

    if not content or len(content) <= 1:
        return "「这个…好像没什么值得记的…」"

    valid_categories = ["character", "event", "location", "preference", "knowledge", "general"]
    if category not in valid_categories:
        category = "general"

    importance = max(1, min(10, importance))
    normalized_importance = importance / 10.0

    # 🆕 如果没有提供 topic，让系统生成（降级方案）
    request_event = Event(
        type=SystemEvent.MEMORY_SEMANTIC_ADDED,
        source="tool.remember",
        data={
            "content": content,
            "importance": normalized_importance,
            "tags": [category],
            "topic_name": topic if topic else None,  # 🆕 传递话题名
        },
    )

    result = await event_bus.request(request_event, timeout=10.0)

    if result and isinstance(result, dict):
        topic_name = result.get("topic_name", topic or "记忆")
        if importance >= 8:
            return f"「这个很重要，我记住了！({topic_name})」"
        else:
            return f"「嗯，记住了～」"

    return "「记住了～」"


@tool(description="回忆之前记住的信息。当你需要引用已知事实时调用")
async def recall(
    keyword: str,
    category: Optional[str] = None,
    page: int = 1,
) -> str:
    """搜索记忆"""
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
            "category": category,
            "page": page,
        },
    )

    result = await event_bus.request(request_event, timeout=10.0)

    if result and isinstance(result, str):
        return result

    return f"「关于 '{keyword}' …我好像没什么印象…」"
