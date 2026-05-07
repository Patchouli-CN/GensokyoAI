"""JSON-compatible RPC dispatch helpers for the GensokyoAI runtime.

This module owns the public method-name mapping for frontend-agnostic runtime
clients. It intentionally contains no transport logic, no UI assumptions, and no
Flutter-specific behavior. Transports such as ``bridge_main.py`` can use this
mapping through :class:`GensokyoAI.runtime.service.RuntimeService`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol


class RuntimeRpcTarget(Protocol):
    """Protocol implemented by runtime services that expose RPC handlers."""

    async def init(self, **kwargs: Any) -> dict[str, Any]: ...

    async def list_characters(self, **kwargs: Any) -> list[dict[str, Any]]: ...

    async def create_session(self, **kwargs: Any) -> dict[str, Any]: ...

    async def list_sessions(self, **kwargs: Any) -> list[dict[str, Any]]: ...

    async def resume_session(self, **kwargs: Any) -> dict[str, Any]: ...

    async def send_message(self, **kwargs: Any) -> dict[str, Any]: ...

    async def shutdown(self, **kwargs: Any) -> dict[str, Any]: ...

    async def health(self, **kwargs: Any) -> dict[str, Any]: ...

    async def info(self, **kwargs: Any) -> dict[str, Any]: ...

    async def dependency_status(self, **kwargs: Any) -> dict[str, Any]: ...

    async def install_dependencies(self, **kwargs: Any) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class RpcMethodSpec:
    """Mapping from public RPC method name to runtime service method name."""

    method: str
    handler_name: str
    legacy: bool = False


RPC_METHOD_SPECS: tuple[RpcMethodSpec, ...] = (
    RpcMethodSpec("runtime.info", "info"),
    RpcMethodSpec("runtime.health", "health"),
    RpcMethodSpec("runtime.shutdown", "shutdown"),
    RpcMethodSpec("agent.init", "init"),
    RpcMethodSpec("agent.send_message", "send_message"),
    RpcMethodSpec("character.list", "list_characters"),
    RpcMethodSpec("session.create", "create_session"),
    RpcMethodSpec("session.list", "list_sessions"),
    RpcMethodSpec("session.resume", "resume_session"),
    RpcMethodSpec("dependency.status", "dependency_status"),
    RpcMethodSpec("dependency.install", "install_dependencies"),
    RpcMethodSpec("init", "init", legacy=True),
    RpcMethodSpec("send_message", "send_message", legacy=True),
    RpcMethodSpec("list_characters", "list_characters", legacy=True),
    RpcMethodSpec("create_session", "create_session", legacy=True),
    RpcMethodSpec("list_sessions", "list_sessions", legacy=True),
    RpcMethodSpec("resume_session", "resume_session", legacy=True),
    RpcMethodSpec("shutdown", "shutdown", legacy=True),
    RpcMethodSpec("dependency_status", "dependency_status", legacy=True),
    RpcMethodSpec("install_dependencies", "install_dependencies", legacy=True),
)


class RpcMethodNotFoundError(ValueError):
    """Raised when a runtime RPC method is not registered."""

    def __init__(self, method: str) -> None:
        super().__init__(f"Unknown method: {method}")
        self.method = method
        self.code = "method_not_found"
        self.details = {"method": method, "allowed_methods": rpc_methods(include_legacy=True)}
        self.recoverable = True


def rpc_methods(*, include_legacy: bool = False) -> list[str]:
    """Return public runtime RPC method names."""

    return [
        spec.method
        for spec in RPC_METHOD_SPECS
        if include_legacy or not spec.legacy
    ]


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
        }
        for spec in RPC_METHOD_SPECS
    ]


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
) -> Any:
    """Dispatch a JSON-compatible RPC request to a runtime service target."""

    handler = resolve_rpc_handler(target, method)
    return await handler(**(params or {}))
