"""工具运行时上下文：按调用隔离的事件总线注入。

替代此前 memory_tool / scene 各自持有的模块级全局单例（`_event_bus`）。
模块级单例意味着整个进程只能有一个事件总线，多个 Agent 实例会互相覆盖——
最后初始化的 Agent 会“抢走”所有工具调用。这挡在“多角色同时对话”功能前面。

现在改为基于 :class:`contextvars.ContextVar`：``ToolExecutor`` 在每次调用工具前
通过 :func:`bind_event_bus` 注入自身持有的事件总线，工具函数通过
:func:`current_event_bus` 读取。``asyncio.gather`` 会为每个并发工具调用复制上下文，
因此并行工具执行天然按调用隔离，不同 Agent 也互不干扰。
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.events import EventBus

# 当前工具调用所归属的事件总线；默认 None（未在工具执行上下文中）。
_event_bus_var: contextvars.ContextVar[EventBus | None] = contextvars.ContextVar(
    "gensokyo_tool_event_bus", default=None
)


@contextmanager
def bind_event_bus(event_bus: EventBus | None) -> Iterator[None]:
    """在当前上下文内绑定事件总线，退出时恢复原值。

    由 ``ToolExecutor`` 在调用工具前后成对使用，保证事件总线按调用生效、
    调用结束即还原，不会跨调用或跨 Agent 泄漏。
    """

    token = _event_bus_var.set(event_bus)
    try:
        yield
    finally:
        _event_bus_var.reset(token)


def current_event_bus() -> EventBus | None:
    """返回当前工具调用上下文中的事件总线（未绑定时为 None）。"""

    return _event_bus_var.get()


def set_event_bus(event_bus: EventBus | None) -> None:
    """遗留兼容入口：直接设置当前上下文的事件总线（不自动恢复）。

    仅为兼容早期直接调用 ``set_event_bus`` 的代码而保留；正常调用链应依赖
    ``ToolExecutor`` 的 :func:`bind_event_bus` 按调用注入。
    """

    _event_bus_var.set(event_bus)
