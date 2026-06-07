import asyncio
import unittest

from GensokyoAI.core.agent.initiative_timer import InitiativeTimerManager
from GensokyoAI.core.agent.types import UnifiedMessage, UnifiedResponse
from GensokyoAI.core.config import InitiativeTimerConfig
from GensokyoAI.core.events import EventBus, SystemEvent
from GensokyoAI.memory.working import WorkingMemoryManager


class _FakeModelClient:
    async def chat(self, messages, options=None):
        return UnifiedResponse(
            message=UnifiedMessage(
                role="assistant",
                content='{"should_schedule": true, "delay_seconds": 60, "message": "我稍后再和你说一句。", "reason": "想补充"}',
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
                        max_pending_message_chars=50,
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
                self.assertEqual(payload["pending_message"], "我稍后再和你说一句。")

                updated = await manager.update(
                    timer_id=payload["timer_id"],
                    delay_seconds=30,
                    pending_message="用户编辑后的积存消息",
                )
                self.assertTrue(updated["user_modified"])
                self.assertEqual(updated["delay_seconds"], 30)
                self.assertEqual(updated["pending_message"], "用户编辑后的积存消息")
                self.assertGreater(updated["generation"], payload["generation"])

                triggered = await manager.trigger(timer_id=payload["timer_id"])
                self.assertTrue(triggered["triggered"])
                self.assertEqual(triggered["message"], "用户编辑后的积存消息")
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


if __name__ == "__main__":
    unittest.main()
