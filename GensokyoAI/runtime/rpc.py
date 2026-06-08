"""JSON-compatible RPC dispatch helpers for the GensokyoAI runtime.

This module owns the public method-name mapping for frontend-agnostic runtime
clients. It intentionally contains no transport logic, no UI assumptions, and no
Flutter-specific behavior. Transports such as ``bridge_main.py`` can use this
mapping through :class:`GensokyoAI.runtime.service.RuntimeService`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from msgspec import Struct

from GensokyoAI.tools.errors import ToolExecutionError
from GensokyoAI.tools.external_manager import ExternalToolSourceStatus

_EXTERNAL_TOOL_STATUS_METHODS: dict[str, str] = {
    ExternalToolSourceStatus.STARTING.value: "external_tool.starting",
    ExternalToolSourceStatus.RUNNING.value: "external_tool.running",
    ExternalToolSourceStatus.STOPPING.value: "external_tool.stopping",
    ExternalToolSourceStatus.FAILED.value: "external_tool.failed",
    ExternalToolSourceStatus.RECONNECTING.value: "external_tool.reconnecting",
}


RuntimeRpcTarget = Any


class RpcMethodSpec(Struct, frozen=True):
    """Mapping from public RPC method name to runtime service method name."""

    method: str
    handler_name: str
    legacy: bool = False
    replacement: str | None = None
    remove_after: str | None = None

    @property
    def namespace(self) -> str:
        """Return the stable method namespace for documentation and clients."""

        return self.method.split(".", 1)[0] if "." in self.method else "legacy"

    @property
    def deprecated(self) -> bool:
        """Return whether this method is deprecated in the current protocol."""

        return self.legacy or self.replacement is not None


RUNTIME_PROTOCOL_VERSION = "1.0.0"
RUNTIME_PROTOCOL_MAJOR_VERSION = 1
RUNTIME_BREAKING_CHANGES: tuple[dict[str, str], ...] = ()


RPC_METHOD_SPECS: tuple[RpcMethodSpec, ...] = (
    RpcMethodSpec("runtime.info", "info"),
    RpcMethodSpec("runtime.health", "health"),
    RpcMethodSpec("runtime.shutdown", "shutdown"),
    RpcMethodSpec("config.validate", "validate_config"),
    RpcMethodSpec("character.validate", "validate_character"),
    RpcMethodSpec("character_package.validate", "validate_character_package"),
    RpcMethodSpec("character_package.preview", "preview_character_package"),
    RpcMethodSpec("character_package.import", "import_character_package"),
    RpcMethodSpec("character_package.export", "export_character_package"),
    RpcMethodSpec("agent.init", "init"),
    RpcMethodSpec("agent.send_message", "send_message"),
    RpcMethodSpec("agent.send_message_stream", "send_message_stream"),
    RpcMethodSpec("character.list", "list_characters"),
    RpcMethodSpec("model.list", "list_models"),
    RpcMethodSpec("model.info", "model_info"),
    RpcMethodSpec("session.create", "create_session"),
    RpcMethodSpec("session.list", "list_sessions"),
    RpcMethodSpec("session.current", "current_session"),
    RpcMethodSpec("session.resume", "resume_session"),
    RpcMethodSpec("session.delete", "delete_session"),
    RpcMethodSpec("session.export", "export_session"),
    RpcMethodSpec("session.rename", "rename_session"),
    RpcMethodSpec("session.messages", "session_messages"),
    RpcMethodSpec("session.replace_messages", "session_replace_messages"),
    RpcMethodSpec("session.regenerate_from", "session_regenerate_from"),
    RpcMethodSpec("session.rollback", "rollback_session"),
    RpcMethodSpec("dependency.status", "dependency_status"),
    RpcMethodSpec("dependency.install", "install_dependencies"),
    RpcMethodSpec("external_tool.status", "external_tool_status"),
    RpcMethodSpec("initiative_timer.current", "initiative_timer_current"),
    RpcMethodSpec("initiative_timer.update", "initiative_timer_update"),
    RpcMethodSpec("initiative_timer.cancel", "initiative_timer_cancel"),
    RpcMethodSpec("initiative_timer.trigger", "initiative_timer_trigger"),
    RpcMethodSpec("initiative_timer.hesitation", "initiative_timer_hesitation"),
    RpcMethodSpec("initiative_timer.hesitation.set", "initiative_timer_hesitation_set"),
    RpcMethodSpec("memory.list", "memory_list"),
    RpcMethodSpec("memory.search", "memory_search"),
    RpcMethodSpec("memory.get", "memory_get"),
    RpcMethodSpec("memory.update", "memory_update"),
    RpcMethodSpec("memory.delete", "memory_delete"),
    RpcMethodSpec("memory.graph", "memory_graph"),
    RpcMethodSpec("init", "init", legacy=True, replacement="agent.init", remove_after="2.0.0"),
    RpcMethodSpec(
        "send_message",
        "send_message",
        legacy=True,
        replacement="agent.send_message",
        remove_after="2.0.0",
    ),
    RpcMethodSpec(
        "send_message_stream",
        "send_message_stream",
        legacy=True,
        replacement="agent.send_message_stream",
        remove_after="2.0.0",
    ),
    RpcMethodSpec(
        "list_characters",
        "list_characters",
        legacy=True,
        replacement="character.list",
        remove_after="2.0.0",
    ),
    RpcMethodSpec(
        "create_session",
        "create_session",
        legacy=True,
        replacement="session.create",
        remove_after="2.0.0",
    ),
    RpcMethodSpec(
        "list_sessions",
        "list_sessions",
        legacy=True,
        replacement="session.list",
        remove_after="2.0.0",
    ),
    RpcMethodSpec(
        "current_session",
        "current_session",
        legacy=True,
        replacement="session.current",
        remove_after="2.0.0",
    ),
    RpcMethodSpec(
        "resume_session",
        "resume_session",
        legacy=True,
        replacement="session.resume",
        remove_after="2.0.0",
    ),
    RpcMethodSpec(
        "delete_session",
        "delete_session",
        legacy=True,
        replacement="session.delete",
        remove_after="2.0.0",
    ),
    RpcMethodSpec(
        "export_session",
        "export_session",
        legacy=True,
        replacement="session.export",
        remove_after="2.0.0",
    ),
    RpcMethodSpec(
        "rename_session",
        "rename_session",
        legacy=True,
        replacement="session.rename",
        remove_after="2.0.0",
    ),
    RpcMethodSpec(
        "rollback_session",
        "rollback_session",
        legacy=True,
        replacement="session.rollback",
        remove_after="2.0.0",
    ),
    RpcMethodSpec(
        "shutdown",
        "shutdown",
        legacy=True,
        replacement="runtime.shutdown",
        remove_after="2.0.0",
    ),
    RpcMethodSpec(
        "dependency_status",
        "dependency_status",
        legacy=True,
        replacement="dependency.status",
        remove_after="2.0.0",
    ),
    RpcMethodSpec(
        "install_dependencies",
        "install_dependencies",
        legacy=True,
        replacement="dependency.install",
        remove_after="2.0.0",
    ),
    RpcMethodSpec(
        "external_tool_status",
        "external_tool_status",
        legacy=True,
        replacement="external_tool.status",
        remove_after="2.0.0",
    ),
)


class RpcError(Exception):
    """Runtime RPC 结构化错误。"""

    def __init__(
        self,
        message: str,
        *,
        code: str = "runtime.error",
        user_message: str | None = None,
        recoverable: bool = True,
        action_hint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.technical_message = message
        self.user_message = user_message or message
        self.recoverable = recoverable
        self.action_hint = action_hint
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "error_code": self.code,
            "message": self.user_message,
            "technical_message": self.technical_message,
            "user_message": self.user_message,
            "recoverable": self.recoverable,
            "action_hint": self.action_hint,
            "details": dict(self.details),
        }


class RpcMethodNotFoundError(ValueError):
    """Raised when a runtime RPC method is not registered."""

    def __init__(self, method: str) -> None:
        super().__init__(f"Unknown method: {method}")
        self.method = method
        self.code = "method_not_found"
        self.technical_message = f"Unknown method: {method}"
        self.user_message = "请求的 Runtime RPC 方法不存在。"
        self.details = {"method": method, "allowed_methods": rpc_methods(include_legacy=True)}
        self.recoverable = True
        self.action_hint = "请改用 runtime.info 返回的 methods 或 legacy_methods 中列出的方法。"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "error_code": self.code,
            "message": self.user_message,
            "technical_message": self.technical_message,
            "user_message": self.user_message,
            "recoverable": self.recoverable,
            "action_hint": self.action_hint,
            "details": dict(self.details),
        }


def rpc_methods(*, include_legacy: bool = False) -> list[str]:
    """Return public runtime RPC method names."""

    return [spec.method for spec in RPC_METHOD_SPECS if include_legacy or not spec.legacy]


def external_tool_status_methods() -> dict[str, str]:
    """Return external tool lifecycle status to Runtime event-name mapping."""

    return dict(_EXTERNAL_TOOL_STATUS_METHODS)


def legacy_rpc_methods() -> list[str]:
    """Return backward-compatible legacy runtime RPC method names."""

    return [spec.method for spec in RPC_METHOD_SPECS if spec.legacy]


def rpc_method_specs() -> list[dict[str, Any]]:
    """Return machine-readable method metadata for documentation clients."""

    return [
        {
            "method": spec.method,
            "handler": spec.handler_name,
            "legacy": spec.legacy,
            "namespace": spec.namespace,
            "deprecated": spec.deprecated,
            "replacement": spec.replacement,
            "remove_after": spec.remove_after,
        }
        for spec in RPC_METHOD_SPECS
    ]


def deprecated_rpc_methods() -> list[dict[str, Any]]:
    """Return deprecated public methods with migration metadata."""

    return [spec for spec in rpc_method_specs() if spec["deprecated"]]


def runtime_protocol_metadata() -> dict[str, Any]:
    """Return versioned Runtime protocol metadata for clients and docs."""

    return {
        "protocol_version": RUNTIME_PROTOCOL_VERSION,
        "protocol_major_version": RUNTIME_PROTOCOL_MAJOR_VERSION,
        "deprecated_methods": deprecated_rpc_methods(),
        "breaking_changes": [dict(change) for change in RUNTIME_BREAKING_CHANGES],
    }


def runtime_error_to_dict(error: Exception) -> dict[str, Any]:
    """将 Runtime 边界异常规范化为兼容旧字符串字段的结构化错误。"""
    to_dict = getattr(error, "to_dict", None)
    if callable(to_dict):
        data = to_dict()
        if isinstance(data, dict):
            data.setdefault("message", str(error))
            data.setdefault("error", data.get("technical_message") or str(error))
            return data

    if isinstance(error, ToolExecutionError):
        data = error.error.to_dict()
        data["code"] = data["error_code"]
        data["message"] = data["user_message"]
        data["error"] = data["technical_message"]
        return data

    code = getattr(error, "code", "runtime.error")
    details = getattr(error, "details", {}) or {}
    recoverable = getattr(error, "recoverable", True)
    technical_message = getattr(error, "technical_message", str(error))
    user_message = getattr(error, "user_message", str(error))
    action_hint = getattr(error, "action_hint", None)
    return {
        "code": code,
        "error_code": code,
        "message": user_message,
        "error": technical_message,
        "technical_message": technical_message,
        "user_message": user_message,
        "recoverable": recoverable,
        "action_hint": action_hint,
        "details": dict(details) if isinstance(details, dict) else {"details": details},
    }


def runtime_error_response(error: Exception) -> dict[str, Any]:
    """构造 Runtime RPC 错误返回，保留旧 error 字符串并新增结构化 error_object。"""
    error_object = runtime_error_to_dict(error)
    return {
        "ok": False,
        "error": error_object.get("error") or error_object.get("technical_message") or str(error),
        "error_code": error_object.get("error_code") or error_object.get("code"),
        "error_object": error_object,
    }


def resolve_rpc_handler(
    target: RuntimeRpcTarget,
    method: str,
) -> Callable[..., Awaitable[Any]]:
    """Resolve a public RPC method name to an async handler on ``target``."""

    for spec in RPC_METHOD_SPECS:
        if spec.method == method:
            handler = getattr(target, spec.handler_name)
            return handler
    raise RpcMethodNotFoundError(method)


async def dispatch_rpc(
    target: RuntimeRpcTarget,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    structured_errors: bool = False,
) -> Any:
    """Dispatch a JSON-compatible RPC request to a runtime service target."""

    try:
        handler = resolve_rpc_handler(target, method)
        return await handler(**(params or {}))
    except Exception as error:
        if structured_errors:
            return runtime_error_response(error)
        raise
