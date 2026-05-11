"""HTTP and WebSocket Runtime adapter built on aiohttp.

This module exposes the frontend-agnostic RuntimeService through network
transports without coupling clients to Agent internals.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from aiohttp import WSMsgType, web

from GensokyoAI.runtime.rpc import runtime_error_to_dict
from GensokyoAI.runtime.service import RuntimeService

RUNTIME_SERVICE_APP_KEY: web.AppKey[RuntimeService] = web.AppKey(
    "runtime_service",
    RuntimeService,
)

DEFAULT_WS_HEARTBEAT_INTERVAL = 30.0


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
    app.router.add_get("/events", handle_events)
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


async def handle_events(request: web.Request) -> web.StreamResponse:
    service = request.app[RUNTIME_SERVICE_APP_KEY]
    subscription = await service.create_event_subscription(**_event_subscription_params_from_request(request))
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
                await response.drain()
            finally:
                queue.task_done()
    except (asyncio.CancelledError, ConnectionResetError, RuntimeError):
        pass
    finally:
        try:
            await service.close_event_subscription(subscription_id)
        except Exception:
            pass

    return response


async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
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
            await _start_streaming_rpc_task(ws, service, request_id, params, send_lock, stream_tasks)
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
    return {"stream_id": stream_id, "cancel_requested": True}


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
                "ts": datetime.now(timezone.utc).isoformat(),
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
        try:
            await service.close_event_subscription(subscription_id)
        except Exception:
            pass
    subscription_tasks.clear()


async def _await_cancelled_task(task: asyncio.Task[Any]) -> None:
    try:
        await task
    except asyncio.CancelledError:
        pass


async def _send_ws_json(
    ws: web.WebSocketResponse,
    send_lock: asyncio.Lock,
    payload: dict[str, Any],
) -> None:
    async with send_lock:
        await ws.send_str(_json_dumps(payload))


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
    return f"event: {event_name}\ndata: {data}\n\n".encode("utf-8")


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
