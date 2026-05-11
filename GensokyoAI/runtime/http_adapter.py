"""HTTP and WebSocket Runtime adapter built on aiohttp.

This module exposes the frontend-agnostic RuntimeService through network
transports without coupling clients to Agent internals.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

from GensokyoAI.runtime.rpc import runtime_error_to_dict
from GensokyoAI.runtime.service import RuntimeService

RUNTIME_SERVICE_APP_KEY: web.AppKey[RuntimeService] = web.AppKey(
    "runtime_service",
    RuntimeService,
)


def json_default(value: Any) -> str:
    return str(value)


def json_response(payload: dict[str, Any], *, status: int = 200) -> web.Response:
    return web.json_response(payload, status=status, dumps=_json_dumps)


def rpc_success(request_id: Any, result: Any) -> dict[str, Any]:
    return {"id": request_id, "ok": True, "result": result}


def rpc_error(request_id: Any, error: Exception) -> dict[str, Any]:
    return {
        "id": request_id,
        "ok": False,
        "error": runtime_error_to_dict(error),
    }


def parse_rpc_payload(payload: Any) -> tuple[Any, str, dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("RPC request payload must be an object")
    request_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params", {})
    if not isinstance(method, str):
        raise ValueError("RPC request field 'method' must be a string")
    if not isinstance(params, dict):
        raise ValueError("RPC request field 'params' must be an object")
    return request_id, method, params


def create_app(
    root_dir: Path | None = None,
    *,
    service: RuntimeService | None = None,
) -> web.Application:
    app = web.Application()
    app[RUNTIME_SERVICE_APP_KEY] = service or RuntimeService(root_dir=root_dir)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/info", handle_info)
    app.router.add_post("/rpc", handle_rpc)
    app.router.add_get("/ws", handle_ws)
    app.on_cleanup.append(cleanup_runtime_service)
    return app


async def cleanup_runtime_service(app: web.Application) -> None:
    await app[RUNTIME_SERVICE_APP_KEY].shutdown()


async def handle_health(request: web.Request) -> web.Response:
    result = await request.app[RUNTIME_SERVICE_APP_KEY].health()
    return json_response(result)


async def handle_info(request: web.Request) -> web.Response:
    result = await request.app[RUNTIME_SERVICE_APP_KEY].info()
    return json_response(result)


async def handle_rpc(request: web.Request) -> web.Response:
    request_id: Any = None
    try:
        payload = await request.json()
        request_id, method, params = parse_rpc_payload(payload)
        result = await request.app[RUNTIME_SERVICE_APP_KEY].handle(method, params)
        return json_response(rpc_success(request_id, result))
    except Exception as error:
        status = 400 if request_id is None else 200
        return json_response(rpc_error(request_id, error), status=status)


async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    service = request.app[RUNTIME_SERVICE_APP_KEY]

    async for message in ws:
        if message.type == WSMsgType.TEXT:
            await _handle_ws_text(ws, service, message.data)
        elif message.type == WSMsgType.ERROR:
            break

    return ws


async def _handle_ws_text(
    ws: web.WebSocketResponse,
    service: RuntimeService,
    data: str,
) -> None:
    request_id: Any = None
    try:
        payload = json.loads(data)
        request_id, method, params = parse_rpc_payload(payload)
        if method == "agent.send_message_stream":
            await _send_streaming_rpc_frames(ws, service, request_id, params)
            return

        result = await service.handle(method, params)
        await ws.send_str(_json_dumps(rpc_success(request_id, result)))
    except Exception as error:
        await ws.send_str(_json_dumps(rpc_error(request_id, error)))


async def _send_streaming_rpc_frames(
    ws: web.WebSocketResponse,
    service: RuntimeService,
    request_id: Any,
    params: dict[str, Any],
) -> None:
    result = await service.send_message_stream(**params)
    for event in result.get("events", []):
        await ws.send_str(
            _json_dumps(
                {
                    "id": request_id,
                    "ok": True,
                    "event": event,
                }
            )
        )
    await ws.send_str(
        _json_dumps(
            {
                "id": request_id,
                "ok": True,
                "done": True,
                "result": result,
            }
        )
    )


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=json_default)
