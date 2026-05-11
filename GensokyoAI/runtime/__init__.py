"""Runtime API boundary for frontend-agnostic GensokyoAI clients."""

from .dependencies import (
    OPTIONAL_PROVIDER_DEPENDENCIES,
    PROVIDER_IMPORTS,
    DependencyError,
    available_dependency_providers,
    dependency_status,
    install_dependencies,
)
from .event_contract import (
    REDACTED_VALUE,
    RUNTIME_EVENT_CONTRACT,
    RuntimeEventSpec,
    runtime_event_contract_payload,
    sanitize_event_payload,
)
from .rpc import (
    RPC_METHOD_SPECS,
    RpcMethodNotFoundError,
    RpcMethodSpec,
    dispatch_rpc,
    external_tool_status_methods,
    legacy_rpc_methods,
    resolve_rpc_handler,
    rpc_method_specs,
    rpc_methods,
)

__all__ = [
    "REDACTED_VALUE",
    "RUNTIME_EVENT_CONTRACT",
    "RuntimeEventSpec",
    "RPC_METHOD_SPECS",
    "RpcMethodNotFoundError",
    "RpcMethodSpec",
    "OPTIONAL_PROVIDER_DEPENDENCIES",
    "PROVIDER_IMPORTS",
    "DependencyError",
    "available_dependency_providers",
    "dependency_status",
    "dispatch_rpc",
    "external_tool_status_methods",
    "install_dependencies",
    "legacy_rpc_methods",
    "resolve_rpc_handler",
    "rpc_method_specs",
    "rpc_methods",
    "runtime_event_contract_payload",
    "sanitize_event_payload",
]
