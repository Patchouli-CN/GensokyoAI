"""工具运行时上下文（事件总线按调用注入）测试。

覆盖 tools/tool_context.py 与 ToolExecutor 的按调用注入：验证事件总线不再是
进程级全局单例，多个 Agent / ToolExecutor 并发时互不覆盖。
"""

import asyncio
import unittest

from GensokyoAI.core.events import EventBus
from GensokyoAI.tools.base import tool
from GensokyoAI.tools.executor import ToolExecutor
from GensokyoAI.tools.registry import ToolRegistry
from GensokyoAI.tools.tool_context import (
    bind_event_bus,
    current_event_bus,
)


class ToolContextBindingTests(unittest.TestCase):
    def test_current_event_bus_defaults_to_none(self):
        self.assertIsNone(current_event_bus())

    def test_bind_event_bus_sets_and_restores(self):
        bus = EventBus(enable_trace=False)
        self.assertIsNone(current_event_bus())
        with bind_event_bus(bus):
            self.assertIs(current_event_bus(), bus)
        # 退出后恢复原值，不泄漏
        self.assertIsNone(current_event_bus())

    def test_bind_event_bus_nesting_restores_outer(self):
        outer = EventBus(enable_trace=False)
        inner = EventBus(enable_trace=False)
        with bind_event_bus(outer):
            self.assertIs(current_event_bus(), outer)
            with bind_event_bus(inner):
                self.assertIs(current_event_bus(), inner)
            self.assertIs(current_event_bus(), outer)
        self.assertIsNone(current_event_bus())


class ToolContextConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_binds_do_not_clobber_each_other(self):
        """并发两路各自绑定不同事件总线，交错执行后仍各自读到自己的总线。

        这是“多角色同时对话”的核心保证：asyncio 会为每个 Task 复制上下文，
        因此 gather 出去的并发工具调用不会互相覆盖事件总线。
        """

        bus_a = EventBus(enable_trace=False)
        bus_b = EventBus(enable_trace=False)

        async def observe(bus: EventBus) -> EventBus | None:
            with bind_event_bus(bus):
                # 让出事件循环，制造交错
                await asyncio.sleep(0)
                seen = current_event_bus()
                await asyncio.sleep(0)
                # 交错后仍应是自己的总线
                assert current_event_bus() is seen
                return seen

        seen_a, seen_b = await asyncio.gather(observe(bus_a), observe(bus_b))
        self.assertIs(seen_a, bus_a)
        self.assertIs(seen_b, bus_b)
        # 并发调用结束后主上下文不受影响
        self.assertIsNone(current_event_bus())


class ToolExecutorInjectionTests(unittest.IsolatedAsyncioTestCase):
    def _probe_registry(self, sink: dict) -> ToolRegistry:
        registry = ToolRegistry()

        @tool(name="__probe_event_bus")
        async def probe() -> str:
            sink["bus"] = current_event_bus()
            return "ok"

        registry.register(probe, name="__probe_event_bus")
        return registry

    async def test_executor_injects_its_own_event_bus_per_call(self):
        sink: dict = {}
        bus = EventBus(enable_trace=False)
        executor = ToolExecutor(registry=self._probe_registry(sink), event_bus=bus)

        await executor.execute({"id": "1", "name": "__probe_event_bus", "arguments": {}})

        # 工具执行期间读到的是该 executor 自己的总线
        self.assertIs(sink["bus"], bus)
        # 调用结束后上下文已还原，不泄漏到调用方
        self.assertIsNone(current_event_bus())

    async def test_two_executors_route_to_their_own_bus_concurrently(self):
        sink_a: dict = {}
        sink_b: dict = {}
        bus_a = EventBus(enable_trace=False)
        bus_b = EventBus(enable_trace=False)
        exec_a = ToolExecutor(registry=self._probe_registry(sink_a), event_bus=bus_a)
        exec_b = ToolExecutor(registry=self._probe_registry(sink_b), event_bus=bus_b)

        await asyncio.gather(
            exec_a.execute({"id": "1", "name": "__probe_event_bus", "arguments": {}}),
            exec_b.execute({"id": "2", "name": "__probe_event_bus", "arguments": {}}),
        )

        # 两个 executor 各自路由到自己的事件总线，互不覆盖
        self.assertIs(sink_a["bus"], bus_a)
        self.assertIs(sink_b["bus"], bus_b)


if __name__ == "__main__":
    unittest.main()
