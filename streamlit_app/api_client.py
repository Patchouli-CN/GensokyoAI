"""
GensokyoAI Runtime 客户端。

- 普通 RPC:HTTP POST /rpc(简快)
- 流式 RPC:WebSocket /ws(发送 agent.send_message_stream,逐 event 接收)
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import aiohttp


class GensokyoRuntimeError(Exception):
    """Runtime 返回的错误。"""

    def __init__(self, message: str, code: str | None = None, details: Any = None):
        super().__init__(message)
        self.code = code
        self.details = details


class GensokyoRuntimeClient:
    """对 GensokyoAI Runtime HTTP / WebSocket 入口的薄封装。"""

    def __init__(
        self,
        http_url: str = "http://127.0.0.1:8765",
        ws_url: str = "ws://127.0.0.1:8765/ws",
        timeout: float = 60.0,
    ):
        self.http_url = http_url.rstrip("/")
        self.ws_url = ws_url
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    # ---------- 普通 RPC ----------
    async def call(self, method: str, params: dict | None = None) -> Any:
        payload = {"id": None, "method": method, "params": params or {}}
        async with (
            aiohttp.ClientSession(timeout=self.timeout) as session,
            session.post(f"{self.http_url}/rpc", json=payload) as resp,
        ):
            data = await resp.json(content_type=None)
        if not data.get("ok"):
            err = data.get("error") or {}
            raise GensokyoRuntimeError(
                err.get("message", "Unknown Runtime error"),
                code=err.get("code"),
                details=err.get("details"),
            )
        return data.get("result")

    async def health(self) -> dict:
        async with (
            aiohttp.ClientSession(timeout=self.timeout) as session,
            session.get(f"{self.http_url}/health") as resp,
        ):
            return await resp.json(content_type=None)

    async def info(self) -> dict:
        async with (
            aiohttp.ClientSession(timeout=self.timeout) as session,
            session.get(f"{self.http_url}/info") as resp,
        ):
            return await resp.json(content_type=None)

    # ---------- 普通 RPC ----------
    async def send_message(self, message: str) -> dict:
        """非流式发消息,返回后端原始 result(让上层决定怎么取 content)。"""
        return await self.call(
            "agent.send_message",
            {"message": message},
        )

    # ---------- 流式 RPC ----------
    async def send_message_stream(
        self,
        params: dict,
        request_id: Any = 1,
    ) -> AsyncIterator[dict]:
        """
        通过 WebSocket 调 agent.send_message_stream。
        yield: 每个 event 字典(type=content / reasoning / tool_call / finish / error / ...)
        """
        async with (
            aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None)) as session,
            session.ws_connect(self.ws_url) as ws,
        ):
            req = {
                "id": request_id,
                "method": "agent.send_message_stream",
                "params": params,
            }
            await ws.send_json(req)

            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    break
                data = json.loads(msg.data)
                if data.get("id") != request_id:
                    # 其它请求的回包,忽略
                    continue
                if not data.get("ok"):
                    err = data.get("error") or {}
                    raise GensokyoRuntimeError(
                        err.get("message", "Stream error"),
                        code=err.get("code"),
                        details=err.get("details"),
                    )
                event = data.get("event")
                if event is None:
                    # 最终汇总(本服务正常不会发,但保险)
                    continue
                yield event
                if event.get("type") in ("finish", "error", "cancelled"):
                    return
