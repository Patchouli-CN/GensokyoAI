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
    current_tool_context,
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
            sink["ctx"] = current_tool_context()
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

    async def test_executor_binds_actor_identity(self):
        sink: dict = {}
        bus = EventBus(enable_trace=False)
        executor = ToolExecutor(
            registry=self._probe_registry(sink),
            event_bus=bus,
            actor_id="marisa",
            world_id="gensokyo",
        )

        await executor.execute({"id": "1", "name": "__probe_event_bus", "arguments": {}})

        # 工具执行期间可读到完整运行时上下文（身份 + 总线）
        self.assertIsNotNone(sink["ctx"])
        self.assertEqual(sink["ctx"].actor_id, "marisa")
        self.assertEqual(sink["ctx"].world_id, "gensokyo")
        self.assertIs(sink["ctx"].event_bus, bus)
        # 调用结束后上下文已还原
        self.assertIsNone(current_tool_context())

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


class ToolBatchParallelSafetyTests(unittest.IsolatedAsyncioTestCase):
    """验证 execute_batch：只读工具并发，写状态工具按序串行。"""

    def _make_executor(self, trace: dict) -> ToolExecutor:
        registry = ToolRegistry()
        # 记录并发度与调用顺序，用于区分并行 / 串行执行
        trace.setdefault("active", 0)
        trace.setdefault("max_active", 0)
        trace.setdefault("order", [])

        async def _run(kind: str, idx: str) -> str:
            trace["active"] += 1
            trace["max_active"] = max(trace["max_active"], trace["active"])
            trace["order"].append(idx)
            try:
                await asyncio.sleep(0.02)  # 制造重叠窗口
            finally:
                trace["active"] -= 1
            return f"{kind}:{idx}"

        async def parallel_probe(idx: str = "") -> str:
            return await _run("parallel", idx)

        async def serial_probe(idx: str = "") -> str:
            return await _run("serial", idx)

        registry.register(parallel_probe, name="__parallel_probe", parallel_safe=True)
        registry.register(serial_probe, name="__serial_probe", parallel_safe=False)
        return ToolExecutor(registry=registry, event_bus=EventBus(enable_trace=False))

    async def test_parallel_safe_tools_run_concurrently(self):
        trace: dict = {}
        executor = self._make_executor(trace)
        calls = [
            {"id": str(i), "name": "__parallel_probe", "arguments": {"idx": str(i)}}
            for i in range(4)
        ]

        results = await executor.execute_batch(calls)

        # 并行工具应重叠执行（并发度 > 1）
        self.assertGreater(trace["max_active"], 1)
        self.assertEqual(len(results), 4)

    async def test_serial_tools_never_overlap_and_keep_order(self):
        trace: dict = {}
        executor = self._make_executor(trace)
        calls = [
            {"id": str(i), "name": "__serial_probe", "arguments": {"idx": str(i)}} for i in range(4)
        ]

        results = await executor.execute_batch(calls)

        # 写状态工具绝不重叠（并发度恒为 1），且按调用顺序执行
        self.assertEqual(trace["max_active"], 1)
        self.assertEqual(trace["order"], ["0", "1", "2", "3"])
        self.assertEqual(len(results), 4)

    async def test_mixed_batch_preserves_result_order_by_index(self):
        trace: dict = {}
        executor = self._make_executor(trace)
        # 交错排列：偶数并行、奇数串行
        calls = []
        for i in range(4):
            name = "__parallel_probe" if i % 2 == 0 else "__serial_probe"
            calls.append({"id": str(i), "name": name, "arguments": {"idx": str(i)}})

        results = await executor.execute_batch(calls)

        # 返回顺序必须与入参一致（按 tool_call_id 对齐）
        self.assertEqual([r["tool_call_id"] for r in results], ["0", "1", "2", "3"])
        # 串行工具仍互不重叠
        self.assertEqual(len(results), 4)


if __name__ == "__main__":
    unittest.main()
