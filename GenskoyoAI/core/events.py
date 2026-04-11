"""异步事件总线"""

import asyncio
from typing import Callable, Any
from msgspec import Struct, field
from enum import Enum, auto
from .exceptions import GenskoyoError


class EventPriority(Enum):
    """事件优先级"""

    HIGHEST = auto()
    HIGH = auto()
    NORMAL = auto()
    LOW = auto()
    LOWEST = auto()


class Event(Struct):
    """事件"""

    name: str
    data: Any = None
    source: str | None = None


class Subscription:
    """订阅 - 不能用 Struct 因为包含不可序列化的 Callable"""

    def __init__(
        self,
        handler: Callable,
        priority: EventPriority = EventPriority.NORMAL,
        once: bool = False,
    ):
        self.handler = handler
        self.priority = priority
        self.once = once


class EventBus:
    """异步事件总线"""

    def __init__(self):
        self._subscribers: dict[str, list[Subscription]] = {}
        self._lock = asyncio.Lock()

    def subscribe(
        self,
        event_name: str,
        handler: Callable,
        priority: EventPriority = EventPriority.NORMAL,
        once: bool = False,
    ) -> None:
        """订阅事件"""

        async def _wrapper(e: Event):
            if asyncio.iscoroutinefunction(handler):
                await handler(e)
            else:
                handler(e)

        sub = Subscription(_wrapper, priority, once)

        if event_name not in self._subscribers:
            self._subscribers[event_name] = []

        self._subscribers[event_name].append(sub)
        # 按优先级排序
        self._subscribers[event_name].sort(key=lambda s: s.priority.value, reverse=True)

    def unsubscribe(self, event_name: str, handler: Callable) -> bool:
        """取消订阅"""
        if event_name not in self._subscribers:
            return False

        original_len = len(self._subscribers[event_name])
        self._subscribers[event_name] = [
            s for s in self._subscribers[event_name] if s.handler != handler
        ]
        return len(self._subscribers[event_name]) != original_len

    async def publish(self, event: Event) -> list[Any]:
        """发布事件"""
        if event.name not in self._subscribers:
            return []

        results = []
        to_remove = []

        for sub in self._subscribers[event.name]:
            try:
                result = await sub.handler(event)
                results.append(result)
                if sub.once:
                    to_remove.append(sub)
            except Exception as e:
                raise GenskoyoError(f"Event handler error for {event.name}: {e}") from e

        # 清理一次性订阅
        for sub in to_remove:
            self._subscribers[event.name].remove(sub)

        return results

    def clear(self) -> None:
        """清空所有订阅"""
        self._subscribers.clear()
