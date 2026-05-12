import asyncio
import json
import unittest
from typing import Any, cast

from aiohttp import WSMsgType
from aiohttp.test_utils import AioHTTPTestCase, TestClient, TestServer, unittest_run_loop

from GensokyoAI.core.events import Event, EventBus, SystemEvent
from GensokyoAI.runtime.http_adapter import (
    RUNTIME_SERVICE_APP_KEY,
    create_app,
    parse_rpc_payload,
    rpc_error,
    rpc_success,
)


class FakeHttpRuntimeService:
    def __init__(self):
        self.shutdown_called = False
        self.event_bus = EventBus(enable_trace=False)
        self.long_rpc_started = asyncio.Event()
        self.long_rpc_release = asyncio.Event()
        self.long_rpc_finished = asyncio.Event()
        self.long_rpc_cancelled = False
        self.active_long_rpcs = 0
        self.stream_started = asyncio.Event()
        self.stream_cancelled = asyncio.Event()
        self.stream_finished = asyncio.Event()
        self.active_streams = 0
        self.closed_subscription_ids: list[str] = []
        self.last_subscription_id: str | None = None

        async def shutdown(_self):
            return None

        self.agent = type("FakeAgent", (), {"event_bus": self.event_bus, "shutdown": shutdown})()

    async def health(self):
        return {"ok": True, "started": False}

    async def info(self):
        return {"name": "Fake Runtime", "methods": ["runtime.health"]}

    async def handle(self, method, params=None):
        params = params or {}
        if method == "runtime.health":
            return await self.health()
        if method == "runtime.info":
            return await self.info()
        if method == "echo":
            return {"method": method, "params": params}
        if method == "slow_rpc":
            return await self._slow_rpc()
        if method == "explode":
            raise ValueError("boom")
        raise ValueError(f"Unknown method: {method}")

    async def _slow_rpc(self):
        self.active_long_rpcs += 1
        self.long_rpc_started.set()
        try:
            await self.long_rpc_release.wait()
            return {"ok": True}
        except asyncio.CancelledError:
            self.long_rpc_cancelled = True
            raise
        finally:
            self.active_long_rpcs -= 1
            self.long_rpc_finished.set()

    async def iter_message_stream(self, message, system_contexts=None):
        self.active_streams += 1
        self.stream_started.set()
        try:
            yield {"type": "content", "index": 0, "content": "echo:"}
            if message == "slow":
                try:
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    self.stream_cancelled.set()
                    yield {"type": "cancelled", "index": 1, "content": "echo:"}
                    raise
            if message == "fail":
                raise ValueError("stream boom")
            yield {"type": "content", "index": 1, "content": message}
            yield {"type": "finish", "index": 2, "content": f"echo:{message}", "session": None}
        finally:
            self.active_streams -= 1
            self.stream_finished.set()

    async def send_message_stream(self, message, system_contexts=None):
        events = []
        async for event in self.iter_message_stream(message, system_contexts):
            events.append(event)
        return {
            "role": "assistant",
            "content": events[-1]["content"],
            "events": events,
            "session": None,
        }

    async def create_event_subscription(self, event_types=None, categories=None, queue_size=100):
        self.last_subscription_params = {
            "event_types": event_types,
            "categories": categories,
            "queue_size": queue_size,
        }
        subscription = await self.real_service.create_event_subscription(
            event_types, categories, queue_size
        )
        self.last_subscription_id = subscription["subscription_id"]
        return subscription

    async def close_event_subscription(self, subscription_id):
        self.closed_subscription_ids.append(subscription_id)
        return await self.real_service.close_event_subscription(subscription_id)

    @property
    def real_service(self):
        from GensokyoAI.runtime.service import RuntimeService

        service = getattr(self, "_real_service", None)
        if service is None:
            service = RuntimeService()
            cast(Any, service.state).agent = self.agent
            self._real_service = service
        return service

    async def shutdown(self):
        self.shutdown_called = True
        await self.real_service.shutdown()
        return {"ok": True}


class RuntimeHttpAdapterHelperTests(unittest.TestCase):
    def test_parse_rpc_payload_validates_shape(self):
        request_id, method, params = parse_rpc_payload(
            {"id": 1, "method": "runtime.health", "params": {"x": 1}}
        )

        self.assertEqual(request_id, 1)
        self.assertEqual(method, "runtime.health")
        self.assertEqual(params, {"x": 1})

        with self.assertRaises(ValueError):
            parse_rpc_payload({"id": 1, "params": {}})
        with self.assertRaises(ValueError):
            parse_rpc_payload({"id": 1, "method": "x", "params": []})

    def test_rpc_success_and_error_payloads_are_json_compatible(self):
        success = rpc_success("a", {"ok": True})
        error = rpc_error("b", ValueError("bad"))

        self.assertEqual(success, {"id": "a", "ok": True, "result": {"ok": True}})
        self.assertFalse(error["ok"])
        self.assertEqual(error["id"], "b")
        self.assertEqual(error["error"]["code"], "runtime.error")


class RuntimeHttpAdapterAppTests(AioHTTPTestCase):
    async def get_application(self):
        self.fake_service = FakeHttpRuntimeService()
        return create_app(service=cast(Any, self.fake_service))

    @unittest_run_loop
    async def test_get_health_and_info(self):
        health_response = await self.client.get("/health")
        info_response = await self.client.get("/info")

        self.assertEqual(health_response.status, 200)
        self.assertEqual((await health_response.json())["ok"], True)
        self.assertEqual(info_response.status, 200)
        self.assertEqual((await info_response.json())["name"], "Fake Runtime")

    @unittest_run_loop
    async def test_post_rpc_returns_success_and_structured_error(self):
        response = await self.client.post(
            "/rpc",
            json={"id": 7, "method": "echo", "params": {"message": "hi"}},
        )
        payload = await response.json()

        self.assertEqual(response.status, 200)
        self.assertEqual(payload["id"], 7)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["params"], {"message": "hi"})

        error_response = await self.client.post(
            "/rpc",
            json={"id": 8, "method": "explode", "params": {}},
        )
        error_payload = await error_response.json()

        self.assertEqual(error_response.status, 200)
        self.assertEqual(error_payload["id"], 8)
        self.assertFalse(error_payload["ok"])
        self.assertEqual(error_payload["error"]["code"], "runtime.error")

    @unittest_run_loop
    async def test_http_rpc_cancellation_releases_in_flight_handler_state(self):
        task = asyncio.create_task(
            self.client.post(
                "/rpc",
                json={"id": "slow-rpc", "method": "slow_rpc", "params": {}},
            )
        )
        await asyncio.wait_for(self.fake_service.long_rpc_started.wait(), timeout=2)
        self.assertEqual(self.fake_service.active_long_rpcs, 1)

        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.fake_service.long_rpc_release.set()
        await asyncio.wait_for(self.fake_service.long_rpc_finished.wait(), timeout=2)

        self.assertEqual(self.fake_service.active_long_rpcs, 0)

    @unittest_run_loop
    async def test_websocket_returns_normal_rpc_response(self):
        ws = await self.client.ws_connect("/ws")
        await ws.send_str(json.dumps({"id": 1, "method": "echo", "params": {"x": 1}}))
        message = await ws.receive(timeout=2)
        await ws.close()

        self.assertEqual(message.type, WSMsgType.TEXT)
        payload = json.loads(message.data)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["params"], {"x": 1})

    @unittest_run_loop
    async def test_websocket_streaming_rpc_sends_event_frames_then_done(self):
        ws = await self.client.ws_connect("/ws")
        await ws.send_str(
            json.dumps(
                {
                    "id": "stream-1",
                    "method": "agent.send_message_stream",
                    "params": {"message": "hi"},
                }
            )
        )

        frames = []
        for _ in range(4):
            message = await ws.receive(timeout=2)
            self.assertEqual(message.type, WSMsgType.TEXT)
            frames.append(json.loads(message.data))
        await ws.close()

        self.assertEqual([frame["id"] for frame in frames], ["stream-1"] * 4)
        self.assertTrue(all(frame["stream_id"] for frame in frames))
        self.assertEqual(frames[0]["event"], {"type": "content", "index": 0, "content": "echo:"})
        self.assertEqual(frames[1]["event"], {"type": "content", "index": 1, "content": "hi"})
        self.assertEqual(frames[2]["event"]["type"], "finish")
        self.assertTrue(frames[3]["done"])
        self.assertEqual(frames[3]["result"]["content"], "echo:hi")

    @unittest_run_loop
    async def test_websocket_streaming_rpc_sends_error_event_when_iterator_fails(self):
        ws = await self.client.ws_connect("/ws")
        await ws.send_str(
            json.dumps(
                {
                    "id": "stream-fail",
                    "method": "agent.send_message_stream",
                    "params": {"message": "fail"},
                }
            )
        )

        frames = []
        for _ in range(3):
            message = await ws.receive(timeout=2)
            self.assertEqual(message.type, WSMsgType.TEXT)
            frames.append(json.loads(message.data))
        await ws.close()

        self.assertEqual(frames[0]["event"], {"type": "content", "index": 0, "content": "echo:"})
        self.assertEqual(frames[1]["event"]["type"], "error")
        self.assertEqual(frames[1]["event"]["content"], "echo:")
        self.assertEqual(frames[1]["event"]["error"]["code"], "runtime.error")
        self.assertFalse(frames[2]["ok"])
        self.assertEqual(frames[2]["error"]["technical_message"], "stream boom")

    @unittest_run_loop
    async def test_websocket_sends_heartbeat_frame(self):
        ws = await self.client.ws_connect("/ws?heartbeat_interval=0.01")
        message = await ws.receive(timeout=2)
        await ws.close()

        self.assertEqual(message.type, WSMsgType.TEXT)
        payload = json.loads(message.data)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["type"], "heartbeat")
        self.assertIn("ts", payload)

    @unittest_run_loop
    async def test_websocket_can_cancel_streaming_rpc(self):
        ws = await self.client.ws_connect("/ws")
        await ws.send_str(
            json.dumps(
                {
                    "id": "stream-cancel",
                    "method": "agent.send_message_stream",
                    "params": {"message": "slow", "stream_id": "stream-xyz"},
                }
            )
        )
        first_message = await ws.receive(timeout=2)
        first_frame = json.loads(first_message.data)
        self.assertEqual(first_frame["stream_id"], "stream-xyz")
        self.assertEqual(first_frame["event"]["type"], "content")

        await ws.send_str(
            json.dumps(
                {
                    "id": "cancel-1",
                    "method": "runtime.cancel_stream",
                    "params": {"stream_id": "stream-xyz"},
                }
            )
        )
        frame_a = json.loads((await ws.receive(timeout=2)).data)
        frame_b = json.loads((await ws.receive(timeout=2)).data)
        await ws.close()

        frames = [frame_a, frame_b]
        cancel_ack = next(frame for frame in frames if frame.get("id") == "cancel-1")
        cancelled_frame = next(frame for frame in frames if frame.get("stream_id") == "stream-xyz")
        self.assertTrue(cancel_ack["ok"])
        self.assertEqual(cancel_ack["result"]["stream_id"], "stream-xyz")
        self.assertTrue(cancel_ack["result"]["cancel_requested"])
        self.assertEqual(cancelled_frame["event"]["type"], "cancelled")

    @unittest_run_loop
    async def test_websocket_close_cancels_active_streaming_rpc(self):
        ws = await self.client.ws_connect("/ws")
        await ws.send_str(
            json.dumps(
                {
                    "id": "stream-close",
                    "method": "agent.send_message_stream",
                    "params": {"message": "slow", "stream_id": "stream-close-id"},
                }
            )
        )
        first_message = await ws.receive(timeout=2)
        self.assertEqual(json.loads(first_message.data)["event"]["type"], "content")
        self.assertEqual(self.fake_service.active_streams, 1)

        await ws.close()
        await asyncio.wait_for(self.fake_service.stream_finished.wait(), timeout=2)

        self.assertTrue(self.fake_service.stream_cancelled.is_set())
        self.assertEqual(self.fake_service.active_streams, 0)

    @unittest_run_loop
    async def test_websocket_runtime_subscribe_receives_filtered_events_and_unsubscribes(self):
        ws = await self.client.ws_connect("/ws")
        await ws.send_str(
            json.dumps(
                {
                    "id": "sub-1",
                    "method": "runtime.subscribe",
                    "params": {"event_types": ["tool.call.started"]},
                }
            )
        )
        ack_message = await ws.receive(timeout=2)
        ack = json.loads(ack_message.data)
        subscription_id = ack["result"]["subscription_id"]

        await self.fake_service.event_bus._process_event(
            Event(
                type=SystemEvent.MODEL_COMPLETED,
                source="test",
                data={"ignored": True},
            )
        )
        await self.fake_service.event_bus._process_event(
            Event(
                type=SystemEvent.TOOL_CALL_STARTED,
                source="test",
                data={"name": "search"},
            )
        )
        event_message = await ws.receive(timeout=2)
        event_frame = json.loads(event_message.data)

        await ws.send_str(
            json.dumps(
                {
                    "id": "unsub-1",
                    "method": "runtime.unsubscribe",
                    "params": {"subscription_id": subscription_id},
                }
            )
        )
        unsub_message = await ws.receive(timeout=2)
        unsub = json.loads(unsub_message.data)
        await ws.close()

        self.assertTrue(ack["ok"])
        self.assertEqual(ack["result"]["event_types"], ["tool.call.started"])
        self.assertEqual(event_frame["subscription_id"], subscription_id)
        self.assertEqual(event_frame["event"]["type"], "tool.call.started")
        self.assertEqual(event_frame["event"]["data"], {"name": "search"})
        self.assertTrue(unsub["ok"])
        self.assertTrue(unsub["result"]["closed"])
        self.assertEqual(self.fake_service.event_bus.stats["subscriber_count"], 0)

    @unittest_run_loop
    async def test_websocket_runtime_subscription_cleanup_on_close(self):
        ws = await self.client.ws_connect("/ws")
        await ws.send_str(
            json.dumps(
                {
                    "id": "sub-cleanup",
                    "method": "runtime.subscribe",
                    "params": {"event_types": ["tool.call.completed"]},
                }
            )
        )
        ack_message = await ws.receive(timeout=2)
        ack = json.loads(ack_message.data)
        self.assertTrue(ack["ok"])
        self.assertEqual(self.fake_service.event_bus.stats["subscriber_count"], 1)

        await ws.close()
        for _ in range(10):
            if self.fake_service.event_bus.stats["subscriber_count"] == 0:
                break
            await asyncio.sleep(0.01)

        self.assertEqual(self.fake_service.event_bus.stats["subscriber_count"], 0)

    @unittest_run_loop
    async def test_sse_events_endpoint_receives_filtered_event_and_cleans_up(self):
        response = await self.client.get("/events?event_types=tool.call.started&queue_size=2")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Content-Type"], "text/event-stream")

        for _ in range(10):
            if self.fake_service.event_bus.stats["subscriber_count"] == 1:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(
            self.fake_service.last_subscription_params["event_types"], ["tool.call.started"]
        )
        self.assertEqual(self.fake_service.last_subscription_params["queue_size"], 2)

        await self.fake_service.event_bus._process_event(
            Event(
                type=SystemEvent.MODEL_COMPLETED,
                source="test",
                data={"ignored": True},
            )
        )
        await self.fake_service.event_bus._process_event(
            Event(
                type=SystemEvent.TOOL_CALL_STARTED,
                source="test",
                data={"name": "search"},
            )
        )

        event_line = await response.content.readline()
        data_line = await response.content.readline()
        blank_line = await response.content.readline()
        response.close()
        for _ in range(10):
            if self.fake_service.event_bus.stats["subscriber_count"] == 0:
                break
            await asyncio.sleep(0.01)

        self.assertEqual(event_line.decode(), "event: runtime.event\n")
        self.assertTrue(data_line.decode().startswith("data: "))
        payload = json.loads(data_line.decode()[len("data: ") :])
        self.assertEqual(payload["type"], "tool.call.started")
        self.assertEqual(payload["data"], {"name": "search"})
        self.assertEqual(blank_line.decode(), "\n")
        self.assertEqual(self.fake_service.event_bus.stats["subscriber_count"], 0)

    @unittest_run_loop
    async def test_sse_close_is_idempotent_and_removes_subscription_once(self):
        response = await self.client.get("/events?event_types=tool.call.started&queue_size=1")
        self.assertEqual(response.status, 200)
        for _ in range(10):
            if self.fake_service.event_bus.stats["subscriber_count"] == 1:
                break
            await asyncio.sleep(0.01)
        subscription_id = self.fake_service.last_subscription_id
        self.assertIsNotNone(subscription_id)

        response.close()
        response.close()
        for _ in range(10):
            if self.fake_service.event_bus.stats["subscriber_count"] == 0:
                break
            await asyncio.sleep(0.01)

        self.assertEqual(self.fake_service.event_bus.stats["subscriber_count"], 0)
        self.assertEqual(self.fake_service.closed_subscription_ids, [subscription_id])

    @unittest_run_loop
    async def test_websocket_subscription_backpressure_with_heartbeat_cleans_up_on_close(self):
        ws = await self.client.ws_connect("/ws?heartbeat_interval=0.01")
        await ws.send_str(
            json.dumps(
                {
                    "id": "sub-backpressure",
                    "method": "runtime.subscribe",
                    "params": {"event_types": ["tool.call.started"], "queue_size": 1},
                }
            )
        )
        ack = json.loads((await ws.receive(timeout=2)).data)
        self.assertTrue(ack["ok"])

        await self.fake_service.event_bus._process_event(
            Event(type=SystemEvent.TOOL_CALL_STARTED, source="test", data={"name": "first"})
        )
        await self.fake_service.event_bus._process_event(
            Event(type=SystemEvent.TOOL_CALL_STARTED, source="test", data={"name": "second"})
        )
        frames = []
        for _ in range(3):
            message = await ws.receive(timeout=2)
            self.assertEqual(message.type, WSMsgType.TEXT)
            frames.append(json.loads(message.data))
            if any(frame.get("type") == "heartbeat" for frame in frames) and any(
                frame.get("event", {}).get("type")
                in {"tool.call.started", "runtime.backpressure.dropped"}
                for frame in frames
            ):
                break

        await ws.close()
        for _ in range(10):
            if self.fake_service.event_bus.stats["subscriber_count"] == 0:
                break
            await asyncio.sleep(0.01)

        self.assertTrue(any(frame.get("type") == "heartbeat" for frame in frames))
        self.assertTrue(
            any(
                frame.get("event", {}).get("type")
                in {"tool.call.started", "runtime.backpressure.dropped"}
                for frame in frames
            )
        )
        self.assertEqual(self.fake_service.event_bus.stats["subscriber_count"], 0)

    @unittest_run_loop
    async def test_multiple_runtime_apps_keep_events_streams_and_shutdown_isolated(self):
        service_a = FakeHttpRuntimeService()
        service_b = FakeHttpRuntimeService()
        server_a = TestServer(create_app(service=cast(Any, service_a)))
        server_b = TestServer(create_app(service=cast(Any, service_b)))
        client_a = TestClient(server_a)
        client_b = TestClient(server_b)
        await client_a.start_server()
        await client_b.start_server()
        try:
            ws_a = await client_a.ws_connect("/ws")
            ws_b = await client_b.ws_connect("/ws")
            await ws_a.send_str(
                json.dumps(
                    {
                        "id": "sub-a",
                        "method": "runtime.subscribe",
                        "params": {"event_types": ["tool.call.started"]},
                    }
                )
            )
            await ws_b.send_str(
                json.dumps(
                    {
                        "id": "sub-b",
                        "method": "runtime.subscribe",
                        "params": {"event_types": ["tool.call.completed"]},
                    }
                )
            )
            ack_a = json.loads((await ws_a.receive(timeout=2)).data)
            ack_b = json.loads((await ws_b.receive(timeout=2)).data)
            self.assertTrue(ack_a["ok"])
            self.assertTrue(ack_b["ok"])

            await service_a.event_bus._process_event(
                Event(type=SystemEvent.TOOL_CALL_STARTED, source="a", data={"runtime": "a"})
            )
            event_a = json.loads((await ws_a.receive(timeout=2)).data)
            self.assertEqual(event_a["event"]["data"], {"runtime": "a"})

            await ws_a.send_str(
                json.dumps(
                    {
                        "id": "stream-a",
                        "method": "agent.send_message_stream",
                        "params": {"message": "slow", "stream_id": "stream-a"},
                    }
                )
            )
            stream_a = json.loads((await ws_a.receive(timeout=2)).data)
            self.assertEqual(stream_a["stream_id"], "stream-a")
            self.assertEqual(service_a.active_streams, 1)
            self.assertEqual(service_b.active_streams, 0)

            await ws_a.send_str(
                json.dumps(
                    {
                        "id": "unsub-a",
                        "method": "runtime.unsubscribe",
                        "params": {"subscription_id": ack_a["result"]["subscription_id"]},
                    }
                )
            )
            unsub_a = json.loads((await ws_a.receive(timeout=2)).data)
            self.assertTrue(unsub_a["ok"])
            self.assertEqual(service_a.event_bus.stats["subscriber_count"], 0)
            await ws_a.close()
            await asyncio.wait_for(service_a.stream_finished.wait(), timeout=2)
            self.assertTrue(service_a.stream_cancelled.is_set())
            self.assertEqual(service_b.event_bus.stats["subscriber_count"], 1)
            self.assertEqual(service_a.active_streams, 0)
            self.assertEqual(service_b.active_streams, 0)

            await service_b.event_bus._process_event(
                Event(type=SystemEvent.TOOL_CALL_COMPLETED, source="b", data={"runtime": "b"})
            )
            event_b = json.loads((await ws_b.receive(timeout=2)).data)
            self.assertEqual(event_b["event"]["data"], {"runtime": "b"})
            await ws_b.close()
        finally:
            await client_a.close()
            await client_b.close()

        self.assertTrue(service_a.shutdown_called)
        self.assertTrue(service_b.shutdown_called)

    @unittest_run_loop
    async def test_rpc_requires_token_when_auth_enabled(self):
        server = TestServer(
            create_app(service=cast(Any, FakeHttpRuntimeService()), auth_token="secret")
        )
        client = TestClient(server)
        await client.start_server()
        try:
            denied = await client.post(
                "/rpc",
                json={"id": 1, "method": "runtime.health", "params": {}},
            )
            allowed = await client.post(
                "/rpc",
                headers={"Authorization": "Bearer secret"},
                json={"id": 2, "method": "runtime.health", "params": {}},
            )
            denied_payload = await denied.json()
            allowed_payload = await allowed.json()
        finally:
            await client.close()

        self.assertEqual(denied.status, 400)
        self.assertFalse(denied_payload["ok"])
        self.assertEqual(allowed.status, 200)
        self.assertTrue(allowed_payload["ok"])

    @unittest_run_loop
    async def test_origin_allowlist_rejects_cross_origin_request(self):
        server = TestServer(
            create_app(
                service=cast(Any, FakeHttpRuntimeService()),
                allowed_origins=["https://allowed.example"],
            )
        )
        client = TestClient(server)
        await client.start_server()
        try:
            denied = await client.get("/health", headers={"Origin": "https://evil.example"})
            allowed = await client.get("/health", headers={"Origin": "https://allowed.example"})
        finally:
            await client.close()

        self.assertEqual(denied.status, 403)
        self.assertEqual(allowed.status, 200)

    @unittest_run_loop
    async def test_cleanup_shuts_down_runtime_service(self):
        service = cast(Any, self.app[RUNTIME_SERVICE_APP_KEY])
        await self.app.cleanup()

        self.assertTrue(service.shutdown_called)


if __name__ == "__main__":
    unittest.main()
