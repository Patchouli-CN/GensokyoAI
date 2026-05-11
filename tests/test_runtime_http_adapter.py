import json
import unittest
from typing import Any, cast

from aiohttp import WSMsgType
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

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
        if method == "explode":
            raise ValueError("boom")
        raise ValueError(f"Unknown method: {method}")

    async def send_message_stream(self, message, system_contexts=None):
        return {
            "role": "assistant",
            "content": f"echo:{message}",
            "events": [
                {"type": "content", "index": 0, "content": "echo:"},
                {"type": "content", "index": 1, "content": message},
                {"type": "finish", "index": 2, "content": f"echo:{message}"},
            ],
            "session": None,
        }

    async def shutdown(self):
        self.shutdown_called = True
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
        self.assertEqual(frames[0]["event"], {"type": "content", "index": 0, "content": "echo:"})
        self.assertEqual(frames[1]["event"], {"type": "content", "index": 1, "content": "hi"})
        self.assertEqual(frames[2]["event"]["type"], "finish")
        self.assertTrue(frames[3]["done"])
        self.assertEqual(frames[3]["result"]["content"], "echo:hi")

    @unittest_run_loop
    async def test_cleanup_shuts_down_runtime_service(self):
        service = cast(Any, self.app[RUNTIME_SERVICE_APP_KEY])
        await self.app.cleanup()

        self.assertTrue(service.shutdown_called)


if __name__ == "__main__":
    unittest.main()
