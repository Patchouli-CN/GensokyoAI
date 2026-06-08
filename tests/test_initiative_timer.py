import asyncio
import unittest

from GensokyoAI.core.agent.initiative_timer import InitiativeTimerManager
from GensokyoAI.core.agent.types import UnifiedMessage, UnifiedResponse
from GensokyoAI.core.config import InitiativeTimerConfig
from GensokyoAI.core.events import EventBus, SystemEvent
from GensokyoAI.memory.working import WorkingMemoryManager


class _FakeModelClient:
    def __init__(self, content: str | None = None, *, structured_output: bool = False):
        self.content = (
            content
            if content is not None
            else '{"should_schedule": true, "delay_seconds": 60, "summary": "稍后补充刚才话题的一个想法", "reason": "想补充"}'
        )
        self.structured_output = structured_output
        self.last_options = None

    def supports(self, capability: str) -> bool:
        return self.structured_output and capability == "structured_output"

    async def chat(self, messages, options=None):
        self.last_options = options
        return UnifiedResponse(
            message=UnifiedMessage(
                role="assistant",
                content=self.content,
            )
        )


class InitiativeTimerManagerTests(unittest.TestCase):
    def test_schedule_update_trigger_and_discard_flow(self):
        async def run():
            event_bus = EventBus(enable_trace=False)
            events = []
            event_bus.subscribe(
                SystemEvent.INITIATIVE_TIMER_CREATED, lambda event: events.append(event)
            )
            event_bus.subscribe(
                SystemEvent.INITIATIVE_TIMER_UPDATED, lambda event: events.append(event)
            )
            event_bus.subscribe(
                SystemEvent.INITIATIVE_TIMER_TRIGGERED, lambda event: events.append(event)
            )
            await event_bus.start()
            try:
                manager = InitiativeTimerManager(
                    config=InitiativeTimerConfig(
                        min_delay_seconds=10,
                        max_delay_seconds=120,
                        max_pending_summary_chars=50,
                    ),
                    model_client=_FakeModelClient(),
                    event_bus=event_bus,
                    character_name="测试角色",
                    working_memory=WorkingMemoryManager(max_turns=10),
                )

                payload = await manager.schedule_after_response("刚才的回复")
                self.assertIsNotNone(payload)
                assert payload is not None
                self.assertEqual(payload["status"], "scheduled")
                self.assertEqual(payload["delay_seconds"], 60)
                self.assertEqual(payload["pending_summary"], "稍后补充刚才话题的一个想法")

                updated = await manager.update(
                    timer_id=payload["timer_id"],
                    delay_seconds=30,
                    pending_summary="用户编辑后的积存摘要",
                )
                self.assertTrue(updated["user_modified"])
                self.assertEqual(updated["delay_seconds"], 30)
                self.assertEqual(updated["pending_summary"], "用户编辑后的积存摘要")
                self.assertGreater(updated["generation"], payload["generation"])

                triggered = await manager.trigger(timer_id=payload["timer_id"])
                self.assertTrue(triggered["triggered"])
                self.assertEqual(triggered["pending_summary"], "用户编辑后的积存摘要")
                self.assertIsNone(manager.current_payload())

                await asyncio.sleep(0.05)
                event_types = [event.type for event in events]
                self.assertIn(SystemEvent.INITIATIVE_TIMER_CREATED, event_types)
                self.assertIn(SystemEvent.INITIATIVE_TIMER_UPDATED, event_types)
                self.assertIn(SystemEvent.INITIATIVE_TIMER_TRIGGERED, event_types)
            finally:
                await event_bus.stop()

        asyncio.run(run())

    def test_discard_invalidates_current_payload(self):
        async def run():
            event_bus = EventBus(enable_trace=False)
            await event_bus.start()
            try:
                manager = InitiativeTimerManager(
                    config=InitiativeTimerConfig(),
                    model_client=_FakeModelClient(),
                    event_bus=event_bus,
                    character_name="测试角色",
                    working_memory=WorkingMemoryManager(max_turns=10),
                )
                payload = await manager.schedule_after_response("刚才的回复")
                self.assertIsNotNone(payload)
                discarded = await manager.discard(reason="user_message_received", source="user")
                self.assertIsNotNone(discarded)
                assert discarded is not None
                self.assertEqual(discarded["status"], "discarded")
                self.assertIsNone(manager.current_payload())
            finally:
                await event_bus.stop()

        asyncio.run(run())

    def test_invalid_decision_json_triggers_hesitation_by_default(self):
        """默认启用犹豫时，解析失败的 JSON 不再直接放弃，而是进入犹豫链。"""
        async def run():
            event_bus = EventBus(enable_trace=False)
            await event_bus.start()
            try:
                manager = InitiativeTimerManager(
                    config=InitiativeTimerConfig(),
                    model_client=_FakeModelClient(
                        '{"should_schedule": true, "delay_seconds": 60, "summary": "截断的摘要'
                    ),
                    event_bus=event_bus,
                    character_name="测试角色",
                    working_memory=WorkingMemoryManager(max_turns=10),
                )

                payload = await manager.schedule_after_response("刚才的回复")
                # 无效 JSON → 进入犹豫重试，payload 为 reconsider 定时器
                self.assertIsNotNone(payload)
                assert payload is not None
                self.assertEqual(payload["source"], "reconsider")
                self.assertEqual(payload["hesitation_round"], 1)
            finally:
                await event_bus.stop()

        asyncio.run(run())

    def test_invalid_decision_json_returns_none_when_hesitation_disabled(self):
        """关闭犹豫时，无效 JSON 直接放弃（无定时器）。"""
        async def run():
            event_bus = EventBus(enable_trace=False)
            await event_bus.start()
            try:
                manager = InitiativeTimerManager(
                    config=InitiativeTimerConfig(hesitation_max_rounds=0),
                    model_client=_FakeModelClient(
                        '{"should_schedule": true, "delay_seconds": 60, "summary": "截断的摘要'
                    ),
                    event_bus=event_bus,
                    character_name="测试角色",
                    working_memory=WorkingMemoryManager(max_turns=10),
                )

                payload = await manager.schedule_after_response("刚才的回复")
                self.assertIsNone(payload)
                self.assertIsNone(manager.current_payload())
            finally:
                await event_bus.stop()

        asyncio.run(run())

    def test_markdown_wrapped_decision_json_still_schedules_timer(self):
        async def run():
            event_bus = EventBus(enable_trace=False)
            await event_bus.start()
            try:
                manager = InitiativeTimerManager(
                    config=InitiativeTimerConfig(),
                    model_client=_FakeModelClient(
                        "```json\n"
                        '{"should_schedule": true, "delay_seconds": 60, "summary": "Markdown 里的摘要", "reason": "想补充"}'
                        "\n```"
                    ),
                    event_bus=event_bus,
                    character_name="测试角色",
                    working_memory=WorkingMemoryManager(max_turns=10),
                )

                payload = await manager.schedule_after_response("刚才的回复")
                self.assertIsNotNone(payload)
                assert payload is not None
                self.assertEqual(payload["pending_summary"], "Markdown 里的摘要")
            finally:
                await event_bus.stop()

        asyncio.run(run())

    def test_structured_output_options_are_sent_when_supported(self):
        async def run():
            event_bus = EventBus(enable_trace=False)
            await event_bus.start()
            try:
                model_client = _FakeModelClient(structured_output=True)
                manager = InitiativeTimerManager(
                    config=InitiativeTimerConfig(),
                    model_client=model_client,
                    event_bus=event_bus,
                    character_name="测试角色",
                    working_memory=WorkingMemoryManager(max_turns=10),
                )

                payload = await manager.schedule_after_response("刚才的回复")
                self.assertIsNotNone(payload)
                self.assertIsNotNone(model_client.last_options)
                assert model_client.last_options is not None
                response_format = model_client.last_options.get("response_format")
                self.assertEqual(response_format["type"], "json_schema")
                self.assertEqual(
                    response_format["json_schema"]["name"], "initiative_timer_decision"
                )
                self.assertTrue(response_format["json_schema"]["strict"])
            finally:
                await event_bus.stop()

        asyncio.run(run())

    def test_structured_output_options_are_not_sent_when_unsupported(self):
        async def run():
            event_bus = EventBus(enable_trace=False)
            await event_bus.start()
            try:
                model_client = _FakeModelClient(structured_output=False)
                manager = InitiativeTimerManager(
                    config=InitiativeTimerConfig(),
                    model_client=model_client,
                    event_bus=event_bus,
                    character_name="测试角色",
                    working_memory=WorkingMemoryManager(max_turns=10),
                )

                payload = await manager.schedule_after_response("刚才的回复")
                self.assertIsNotNone(payload)
                self.assertIsNotNone(model_client.last_options)
                assert model_client.last_options is not None
                self.assertNotIn("response_format", model_client.last_options)
            finally:
                await event_bus.stop()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
