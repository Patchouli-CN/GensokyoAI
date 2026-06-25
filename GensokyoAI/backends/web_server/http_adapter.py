"""HTTP and WebSocket Runtime adapter built on aiohttp.

This module exposes the frontend-agnostic RuntimeService through network
transports without coupling clients to Agent internals.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from aiohttp import WSMsgType, web
from msgspec import Struct

from GensokyoAI.runtime.rpc import runtime_error_to_dict
from GensokyoAI.runtime.service import RuntimeService
from GensokyoAI.utils.helpers import utc_now

RUNTIME_SERVICE_APP_KEY: web.AppKey[RuntimeService] = web.AppKey(
    "runtime_service",
    RuntimeService,
)

DEFAULT_WS_HEARTBEAT_INTERVAL = 30.0
DEFAULT_MAX_REQUEST_BODY_SIZE = 1024 * 1024
DEFAULT_WS_MAX_MSG_SIZE = 1024 * 1024
MIN_AUTH_TOKEN_LENGTH = 16
AUTH_RATE_LIMIT_MAX_FAILURES = 10
AUTH_RATE_LIMIT_WINDOW_SECONDS = 60.0


class RuntimeHttpSecurityConfig(Struct, frozen=True):
    token: str | None = None
    allowed_origins: tuple[str, ...] = ()
    allow_all_origins: bool = False
    max_request_body_size: int = DEFAULT_MAX_REQUEST_BODY_SIZE

    @property
    def auth_enabled(self) -> bool:
        # 空字符串视为未启用认证，避免 compare_digest("", "") == True 的绕过
        return bool(self.token)


RUNTIME_SECURITY_APP_KEY: web.AppKey[RuntimeHttpSecurityConfig] = web.AppKey(
    "runtime_http_security",
    RuntimeHttpSecurityConfig,
)

RUNTIME_AUTH_RATE_LIMIT_APP_KEY: web.AppKey[dict[str, tuple[int, float]]] = web.AppKey(
    "runtime_auth_rate_limit",
    dict,
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


def _normalize_token(value: str | None) -> str | None:
    """把空字符串规范化为 None，避免空 token 被误认为启用认证。"""

    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def create_app(
    root_dir: Path | None = None,
    *,
    service: RuntimeService | None = None,
    auth_token: str | None = None,
    allowed_origins: list[str] | tuple[str, ...] | None = None,
    allow_all_origins: bool = False,
    max_request_body_size: int = DEFAULT_MAX_REQUEST_BODY_SIZE,
) -> web.Application:
    token = _normalize_token(auth_token or os.environ.get("GENSOKYOAI_RUNTIME_TOKEN"))
    if token is not None and len(token) < MIN_AUTH_TOKEN_LENGTH:
        raise RuntimeError(
            f"Runtime auth token must be at least {MIN_AUTH_TOKEN_LENGTH} characters"
        )

    origins = tuple(allowed_origins or ())
    if origins and "*" in origins:
        allow_all_origins = True
        origins = ()

    app = web.Application(client_max_size=max_request_body_size)
    app[RUNTIME_SERVICE_APP_KEY] = service or RuntimeService(root_dir=root_dir)
    app[RUNTIME_SECURITY_APP_KEY] = RuntimeHttpSecurityConfig(
        token=token,
        allowed_origins=origins,
        allow_all_origins=allow_all_origins,
        max_request_body_size=max_request_body_size,
    )
    app[RUNTIME_AUTH_RATE_LIMIT_APP_KEY] = {}
    app.router.add_get("/health", handle_health)
    app.router.add_get("/info", handle_info)
    app.router.add_post("/rpc", handle_rpc)
    app.router.add_get("/ws", handle_ws)
    app.router.add_get("/events", handle_events)
    app.on_cleanup.append(cleanup_runtime_service)
    return app


async def cleanup_runtime_service(app: web.Application) -> None:
    await app[RUNTIME_SERVICE_APP_KEY].shutdown()


async def handle_health(request: web.Request) -> web.Response:
    _validate_runtime_request(request)
    result = await request.app[RUNTIME_SERVICE_APP_KEY].health()
    return json_response(result)


async def handle_info(request: web.Request) -> web.Response:
    _validate_runtime_request(request)
    result = await request.app[RUNTIME_SERVICE_APP_KEY].info()
    return json_response(result)


async def handle_rpc(request: web.Request) -> web.Response:
    request_id: Any = None
    try:
        _validate_runtime_request(request)
        payload = await request.json()
        request_id, method, params = parse_rpc_payload(payload)
        result = await request.app[RUNTIME_SERVICE_APP_KEY].handle(method, params)
        return json_response(rpc_success(request_id, result))
    except Exception as error:
        status = 400 if request_id is None else 200
        return json_response(rpc_error(request_id, error), status=status)


async def handle_events(request: web.Request) -> web.StreamResponse:
    _validate_runtime_request(request)
    service = request.app[RUNTIME_SERVICE_APP_KEY]
    subscription = await service.create_event_subscription(
        **_event_subscription_params_from_request(request)
    )
    subscription_id = subscription["subscription_id"]
    queue = subscription["queue"]
    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    await response.prepare(request)

    try:
        while True:
            event = await queue.get()
            try:
                await response.write(_sse_frame("runtime.event", event))
                # drain() is deprecated in aiohttp 3.8+, write() already handles buffering
            finally:
                queue.task_done()
    except (asyncio.CancelledError, ConnectionResetError, RuntimeError):
        pass
    finally:
        with contextlib.suppress(Exception):
            await service.close_event_subscription(subscription_id)

    return response


async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    _validate_runtime_request(request)
    ws = web.WebSocketResponse(max_msg_size=DEFAULT_WS_MAX_MSG_SIZE)
    await ws.prepare(request)
    service = request.app[RUNTIME_SERVICE_APP_KEY]
    send_lock = asyncio.Lock()
    subscription_tasks: dict[str, asyncio.Task[None]] = {}
    stream_tasks: dict[str, asyncio.Task[None]] = {}
    heartbeat_interval = _heartbeat_interval_from_request(request)
    heartbeat_task = asyncio.create_task(_pump_ws_heartbeat(ws, send_lock, heartbeat_interval))

    try:
        async for message in ws:
            if message.type == WSMsgType.TEXT:
                await _handle_ws_text(
                    ws,
                    service,
                    message.data,
                    send_lock,
                    subscription_tasks,
                    stream_tasks,
                )
            elif message.type == WSMsgType.ERROR:
                break
    finally:
        heartbeat_task.cancel()
        await _await_cancelled_task(heartbeat_task)
        await _cleanup_ws_streams(stream_tasks)
        await _cleanup_ws_subscriptions(service, subscription_tasks)

    return ws


async def _handle_ws_text(
    ws: web.WebSocketResponse,
    service: RuntimeService,
    data: str,
    send_lock: asyncio.Lock,
    subscription_tasks: dict[str, asyncio.Task[None]] | None = None,
    stream_tasks: dict[str, asyncio.Task[None]] | None = None,
) -> None:
    request_id: Any = None
    try:
        payload = json.loads(data)
        request_id, method, params = parse_rpc_payload(payload)
        if method == "agent.send_message_stream":
            await _start_streaming_rpc_task(
                ws, service, request_id, params, send_lock, stream_tasks
            )
            return
        if method == "runtime.cancel_stream":
            result = await _cancel_streaming_rpc_task(params, stream_tasks)
            await _send_ws_json(ws, send_lock, rpc_success(request_id, result))
            return
        if method == "runtime.subscribe":
            await _start_event_subscription(
                ws,
                service,
                request_id,
                params,
                send_lock,
                subscription_tasks,
            )
            return
        if method == "runtime.unsubscribe":
            result = await _stop_event_subscription(service, params, subscription_tasks)
            await _send_ws_json(ws, send_lock, rpc_success(request_id, result))
            return

        result = await service.handle(method, params)
        await _send_ws_json(ws, send_lock, rpc_success(request_id, result))
    except Exception as error:
        await _send_ws_json(ws, send_lock, rpc_error(request_id, error))


async def _start_streaming_rpc_task(
    ws: web.WebSocketResponse,
    service: RuntimeService,
    request_id: Any,
    params: dict[str, Any],
    send_lock: asyncio.Lock,
    stream_tasks: dict[str, asyncio.Task[None]] | None,
) -> str:
    stream_id = str(params.pop("stream_id", None) or uuid4())
    if stream_tasks is not None and stream_id in stream_tasks:
        raise ValueError(f"Runtime stream already exists: {stream_id}")
    task = asyncio.create_task(
        _send_streaming_rpc_frames(ws, service, request_id, stream_id, params, send_lock)
    )
    if stream_tasks is not None:
        stream_tasks[stream_id] = task
        task.add_done_callback(lambda _task: stream_tasks.pop(stream_id, None))
    return stream_id


async def _cancel_streaming_rpc_task(
    params: dict[str, Any],
    stream_tasks: dict[str, asyncio.Task[None]] | None,
) -> dict[str, Any]:
    stream_id = params.get("stream_id")
    if not isinstance(stream_id, str) or not stream_id:
        raise ValueError("Runtime stream_id is required")
    task = stream_tasks.get(stream_id) if stream_tasks is not None else None
    if task is None:
        raise ValueError(f"Runtime stream does not exist: {stream_id}")
    task.cancel()
    await _await_cancelled_task(task)
    return {"stream_id": stream_id, "cancel_requested": True, "cancelled": task.cancelled()}


async def _send_streaming_rpc_frames(
    ws: web.WebSocketResponse,
    service: RuntimeService,
    request_id: Any,
    stream_id: str,
    params: dict[str, Any],
    send_lock: asyncio.Lock,
) -> None:
    events: list[dict[str, Any]] = []
    final_content = ""
    session_payload: dict[str, Any] | None = None

    try:
        async for event in service.iter_message_stream(**params):
            events.append(event)
            final_content = event.get("content", final_content)
            if event.get("type") == "finish":
                session_payload = event.get("session")
            await _send_ws_json(
                ws,
                send_lock,
                {
                    "id": request_id,
                    "ok": True,
                    "stream_id": stream_id,
                    "event": event,
                },
            )
    except asyncio.CancelledError:
        if not events or events[-1].get("type") != "cancelled":
            cancelled_event = {
                "type": "cancelled",
                "index": len(events),
                "content": final_content,
            }
            events.append(cancelled_event)
            await _send_ws_json(
                ws,
                send_lock,
                {
                    "id": request_id,
                    "ok": True,
                    "stream_id": stream_id,
                    "event": cancelled_event,
                },
            )
        return
    except Exception as error:
        if not events or events[-1].get("type") != "error":
            error_event = {
                "type": "error",
                "index": len(events),
                "content": final_content,
                "error": runtime_error_to_dict(error),
            }
            events.append(error_event)
            await _send_ws_json(
                ws,
                send_lock,
                {
                    "id": request_id,
                    "ok": True,
                    "stream_id": stream_id,
                    "event": error_event,
                },
            )
        await _send_ws_json(ws, send_lock, rpc_error(request_id, error))
        return

    await _send_ws_json(
        ws,
        send_lock,
        {
            "id": request_id,
            "ok": True,
            "stream_id": stream_id,
            "done": True,
            "result": {
                "role": "assistant",
                "content": final_content,
                "events": events,
                "session": session_payload,
            },
        },
    )


async def _start_event_subscription(
    ws: web.WebSocketResponse,
    service: RuntimeService,
    request_id: Any,
    params: dict[str, Any],
    send_lock: asyncio.Lock,
    subscription_tasks: dict[str, asyncio.Task[None]] | None,
) -> None:
    subscription = await service.create_event_subscription(**params)
    subscription_id = subscription["subscription_id"]
    queue = subscription["queue"]
    if subscription_tasks is not None:
        subscription_tasks[subscription_id] = asyncio.create_task(
            _pump_event_subscription(ws, request_id, subscription_id, queue, send_lock)
        )
    result = {
        "subscription_id": subscription_id,
        "event_types": subscription["event_types"],
    }
    await _send_ws_json(ws, send_lock, rpc_success(request_id, result))


async def _stop_event_subscription(
    service: RuntimeService,
    params: dict[str, Any],
    subscription_tasks: dict[str, asyncio.Task[None]] | None,
) -> dict[str, Any]:
    subscription_id = params.get("subscription_id")
    if not isinstance(subscription_id, str) or not subscription_id:
        raise ValueError("Runtime event subscription_id is required")
    task = subscription_tasks.pop(subscription_id, None) if subscription_tasks is not None else None
    if task is not None:
        task.cancel()
        await _await_cancelled_task(task)
    return await service.close_event_subscription(subscription_id)


async def _pump_event_subscription(
    ws: web.WebSocketResponse,
    request_id: Any,
    subscription_id: str,
    queue: asyncio.Queue[dict[str, Any]],
    send_lock: asyncio.Lock,
) -> None:
    while True:
        event = await queue.get()
        try:
            await _send_ws_json(
                ws,
                send_lock,
                {
                    "id": request_id,
                    "ok": True,
                    "subscription_id": subscription_id,
                    "event": event,
                },
            )
        finally:
            queue.task_done()


async def _pump_ws_heartbeat(
    ws: web.WebSocketResponse,
    send_lock: asyncio.Lock,
    interval: float,
) -> None:
    while True:
        await asyncio.sleep(interval)
        await _send_ws_json(
            ws,
            send_lock,
            {
                "ok": True,
                "type": "heartbeat",
                "ts": utc_now().isoformat(),
            },
        )


async def _cleanup_ws_streams(stream_tasks: dict[str, asyncio.Task[None]]) -> None:
    for task in list(stream_tasks.values()):
        task.cancel()
    for task in list(stream_tasks.values()):
        await _await_cancelled_task(task)
    stream_tasks.clear()


async def _cleanup_ws_subscriptions(
    service: RuntimeService,
    subscription_tasks: dict[str, asyncio.Task[None]],
) -> None:
    for subscription_id, task in list(subscription_tasks.items()):
        task.cancel()
        await _await_cancelled_task(task)
        with contextlib.suppress(Exception):
            await service.close_event_subscription(subscription_id)
    subscription_tasks.clear()


async def _await_cancelled_task(task: asyncio.Task[Any]) -> None:
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def _send_ws_json(
    ws: web.WebSocketResponse,
    send_lock: asyncio.Lock,
    payload: dict[str, Any],
) -> None:
    async with send_lock:
        await ws.send_str(_json_dumps(payload))


def _validate_origin(request: web.Request, security: RuntimeHttpSecurityConfig) -> None:
    origin = request.headers.get("Origin")
    if not origin:
        return

    if security.allow_all_origins:
        return

    parsed_origin = urlparse(origin)
    if parsed_origin.scheme not in {"http", "https", "ws", "wss", "file"}:
        raise web.HTTPForbidden(reason="Runtime request origin is not allowed")

    origin_host = parsed_origin.hostname
    if not origin_host:
        raise web.HTTPForbidden(reason="Runtime request origin is not allowed")

    if not security.allowed_origins:
        # 默认未配置 allowed_origins 时，拒绝所有跨域 Origin 请求
        raise web.HTTPForbidden(reason="Runtime request origin is not allowed")

    origin_host_lower = origin_host.lower()
    for allowed in security.allowed_origins:
        allowed_parsed = urlparse(allowed)
        allowed_host = allowed_parsed.hostname
        if not allowed_host:
            continue
        if origin_host_lower == allowed_host.lower():
            return

    raise web.HTTPForbidden(reason="Runtime request origin is not allowed")


def _validate_auth_token(request: web.Request, security: RuntimeHttpSecurityConfig) -> None:
    if not security.auth_enabled:
        return
    expected = security.token or ""
    candidates = []
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        candidates.append(auth_header[len("Bearer ") :].strip())
    header_token = request.headers.get("X-Runtime-Token")
    if header_token:
        candidates.append(header_token.strip())
    if not any(hmac.compare_digest(candidate, expected) for candidate in candidates):
        _record_auth_failure(request)
        raise web.HTTPUnauthorized(reason="Runtime authentication token is required")


def _record_auth_failure(request: web.Request) -> None:
    peer = request.remote or request.headers.get("X-Forwarded-For", "unknown")
    bucket = request.app[RUNTIME_AUTH_RATE_LIMIT_APP_KEY]
    now = time.monotonic()
    count, window_start = bucket.get(peer, (0, now))
    if now - window_start > AUTH_RATE_LIMIT_WINDOW_SECONDS:
        count = 0
        window_start = now
    count += 1
    bucket[peer] = (count, window_start)
    if count > AUTH_RATE_LIMIT_MAX_FAILURES:
        raise web.HTTPTooManyRequests(reason="Too many failed authentication attempts")


def _validate_runtime_request(request: web.Request) -> None:
    security = request.app[RUNTIME_SECURITY_APP_KEY]
    # 先校验 Origin，再校验 token；避免 token 被同源策略无关地泄露
    _validate_origin(request, security)
    _validate_auth_token(request, security)


def _event_subscription_params_from_request(request: web.Request) -> dict[str, Any]:
    params: dict[str, Any] = {}
    event_types = _split_query_values(request.query.getall("event_types", []))
    categories = _split_query_values(request.query.getall("categories", []))
    queue_size = request.query.get("queue_size")
    if event_types:
        params["event_types"] = event_types
    if categories:
        params["categories"] = categories
    if queue_size:
        try:
            params["queue_size"] = int(queue_size)
        except ValueError as error:
            raise ValueError("SSE query parameter 'queue_size' must be an integer") from error
    return params


def _split_query_values(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        result.extend(item.strip() for item in value.split(",") if item.strip())
    return result


def _sse_frame(event_name: str, payload: dict[str, Any]) -> bytes:
    data = _json_dumps(payload)
    return f"event: {event_name}\ndata: {data}\n\n".encode()


def _heartbeat_interval_from_request(request: web.Request) -> float:
    raw_value = request.query.get("heartbeat_interval")
    if raw_value is None:
        return DEFAULT_WS_HEARTBEAT_INTERVAL
    try:
        interval = float(raw_value)
    except ValueError:
        return DEFAULT_WS_HEARTBEAT_INTERVAL
    return max(interval, 0.01)


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=json_default)
