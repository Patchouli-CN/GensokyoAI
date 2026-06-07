"""Runtime Event Contract 元数据与 payload 清洗工具。

该模块定义后端 Runtime 状态事件的稳定字段契约，供客户端、测试与发布端共同引用。
"""

from __future__ import annotations

from typing import Any

from msgspec import Struct

SENSITIVE_FIELD_NAMES = {
    "api_key",
    "apikey",
    "authorization",
    "access_token",
    "refresh_token",
    "token",
    "password",
    "secret",
    "client_secret",
}
REDACTED_VALUE = "[REDACTED]"


class RuntimeEventSpec(Struct, frozen=True):
    """单个 Runtime 事件 payload 契约。"""

    event: str
    required_fields: tuple[str, ...] = ()
    optional_fields: tuple[str, ...] = ()
    description: str = ""


RUNTIME_EVENT_CONTRACT: dict[str, RuntimeEventSpec] = {
    "model.request_started": RuntimeEventSpec(
        event="model.request_started",
        required_fields=("context", "provider", "model"),
        optional_fields=("message_count", "prompt_length"),
        description="模型请求开始。",
    ),
    "model.retry_scheduled": RuntimeEventSpec(
        event="model.retry_scheduled",
        required_fields=("context", "provider", "model", "attempt", "max_attempts"),
        optional_fields=("error", "status_code", "endpoint"),
        description="模型请求即将重试。",
    ),
    "model.first_token": RuntimeEventSpec(
        event="model.first_token",
        required_fields=("context", "provider", "model", "first_token_ms"),
        optional_fields=("first_chunk_ms",),
        description="模型产生首个可见 token。",
    ),
    "model.completed": RuntimeEventSpec(
        event="model.completed",
        required_fields=("context", "provider", "model", "duration_ms"),
        optional_fields=("finish_reason", "usage"),
        description="模型请求完成。",
    ),
    "model.failed": RuntimeEventSpec(
        event="model.failed",
        required_fields=("context", "provider", "model", "error", "error_type"),
        optional_fields=("status_code", "endpoint", "retryable", "timeout"),
        description="模型请求失败。",
    ),
    "tool.call.started": RuntimeEventSpec(
        event="tool.call.started",
        required_fields=("name", "arguments"),
        description="工具调用开始。",
    ),
    "tool.call.progress": RuntimeEventSpec(
        event="tool.call.progress",
        required_fields=("name", "status"),
        optional_fields=("message", "details"),
        description="工具调用进度更新。",
    ),
    "tool.call.completed": RuntimeEventSpec(
        event="tool.call.completed",
        required_fields=("name", "arguments"),
        optional_fields=("result",),
        description="工具调用完成。",
    ),
    "tool.call.failed": RuntimeEventSpec(
        event="tool.call.failed",
        required_fields=("name", "arguments", "error"),
        optional_fields=("error_code", "user_message", "recoverable", "action_hint", "details"),
        description="工具调用失败。",
    ),
    "background.worker.started": RuntimeEventSpec(
        event="background.worker.started",
        required_fields=("worker_id",),
        optional_fields=("queue_size",),
        description="后台 worker 启动。",
    ),
    "background.worker.idle": RuntimeEventSpec(
        event="background.worker.idle",
        required_fields=("worker_id",),
        optional_fields=("queue_size",),
        description="后台 worker 空闲。",
    ),
    "background.worker.failed": RuntimeEventSpec(
        event="background.worker.failed",
        required_fields=("worker_id", "error", "error_type"),
        optional_fields=("task_id", "task_name", "task_type"),
        description="后台 worker 或任务失败。",
    ),
    "model.auth": RuntimeEventSpec(
        event="model.auth",
        required_fields=("status",),
        optional_fields=("context", "provider", "model", "error", "error_type"),
        description="模型认证刷新状态，payload 必须清洗敏感字段。",
    ),
    "initiative_timer.created": RuntimeEventSpec(
        event="initiative_timer.created",
        required_fields=("timer_id", "generation", "status", "due_at", "delay_seconds"),
        optional_fields=("pending_message", "reason", "source", "remaining_seconds"),
        description="主动定时器已创建。",
    ),
    "initiative_timer.updated": RuntimeEventSpec(
        event="initiative_timer.updated",
        required_fields=("timer_id", "generation", "status", "due_at", "delay_seconds"),
        optional_fields=("pending_message", "reason", "source", "remaining_seconds"),
        description="主动定时器已更新。",
    ),
    "initiative_timer.cancelled": RuntimeEventSpec(
        event="initiative_timer.cancelled",
        required_fields=("timer_id", "generation", "status"),
        optional_fields=("reason", "source"),
        description="主动定时器已取消，积存消息已丢弃。",
    ),
    "initiative_timer.triggered": RuntimeEventSpec(
        event="initiative_timer.triggered",
        required_fields=("timer_id", "generation", "status"),
        optional_fields=("message", "source"),
        description="主动定时器已触发，积存消息已发送。",
    ),
    "initiative_timer.discarded": RuntimeEventSpec(
        event="initiative_timer.discarded",
        required_fields=("timer_id", "generation", "status"),
        optional_fields=("reason", "source"),
        description="主动定时器因新消息或替换被丢弃。",
    ),
}


def sanitize_event_payload(payload: Any) -> Any:
    """递归清洗 Runtime 事件 payload 中的敏感字段。"""

    if isinstance(payload, dict):
        cleaned: dict[Any, Any] = {}
        for key, value in payload.items():
            key_text = str(key).lower()
            if key_text in SENSITIVE_FIELD_NAMES or any(
                part in key_text for part in ("api_key", "token", "secret")
            ):
                cleaned[key] = REDACTED_VALUE
            else:
                cleaned[key] = sanitize_event_payload(value)
        return cleaned
    if isinstance(payload, list):
        return [sanitize_event_payload(item) for item in payload]
    if isinstance(payload, tuple):
        return tuple(sanitize_event_payload(item) for item in payload)
    return payload


def runtime_event_contract_payload() -> dict[str, dict[str, Any]]:
    """返回 JSON-compatible 的事件契约元数据。"""

    return {
        name: {
            "event": spec.event,
            "required_fields": list(spec.required_fields),
            "optional_fields": list(spec.optional_fields),
            "description": spec.description,
        }
        for name, spec in sorted(RUNTIME_EVENT_CONTRACT.items())
    }


__all__ = [
    "REDACTED_VALUE",
    "RUNTIME_EVENT_CONTRACT",
    "RuntimeEventSpec",
    "SENSITIVE_FIELD_NAMES",
    "runtime_event_contract_payload",
    "sanitize_event_payload",
]
