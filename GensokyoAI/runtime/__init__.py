"""Runtime API boundary for frontend-agnostic GensokyoAI clients."""

from .rpc import (
    RPC_METHOD_SPECS,
    RpcMethodNotFoundError,
    RpcMethodSpec,
    dispatch_rpc,
    legacy_rpc_methods,
    resolve_rpc_handler,
    rpc_method_specs,
    rpc_methods,
)
from .dependencies import (
    OPTIONAL_PROVIDER_DEPENDENCIES,
    PROVIDER_IMPORTS,
    DependencyError,
    available_dependency_providers,
    dependency_status,
    install_dependencies,
)
from .service import RuntimeService, RuntimeState

__all__ = [
    "RPC_METHOD_SPECS",
    "RpcMethodNotFoundError",
    "RpcMethodSpec",
    "OPTIONAL_PROVIDER_DEPENDENCIES",
    "PROVIDER_IMPORTS",
    "DependencyError",
    "RuntimeService",
    "RuntimeState",
    "available_dependency_providers",
    "dependency_status",
    "dispatch_rpc",
    "install_dependencies",
    "legacy_rpc_methods",
    "resolve_rpc_handler",
    "rpc_method_specs",
    "rpc_methods",
]
