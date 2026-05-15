"""Optional Provider dependency detection and installation helpers.

This module belongs to the frontend-agnostic runtime boundary. Clients may ask
for Provider dependencies by Provider name only; arbitrary package names or shell
commands are intentionally not accepted.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Iterable
from typing import Any, Literal

from msgspec import Struct

OPTIONAL_PROVIDER_DEPENDENCIES: dict[str, list[str]] = {
    "ollama": ["ollama"],
    "openai": ["openai>=1.0.0"],
    "openrouter": ["openai>=1.0.0"],
    "deepseek": ["openai>=1.0.0"],
    "openai_responses": ["openai>=1.0.0"],
    "claude": ["anthropic>=0.20.0"],
    "gemini": ["google-genai>=1.0.0"],
}

PROVIDER_IMPORTS: dict[str, list[str]] = {
    "ollama": ["ollama"],
    "openai": ["openai"],
    "openrouter": ["openai"],
    "deepseek": ["openai"],
    "openai_responses": ["openai"],
    "claude": ["anthropic"],
    "gemini": ["google.genai"],
}

InstallScope = Literal["current_runtime"]


class DependencyError(RuntimeError):
    """Raised when dependency operations violate runtime dependency policy."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "dependency_error",
        details: dict[str, Any] | None = None,
        recoverable: bool = True,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}
        self.recoverable = recoverable


class ProviderDependencyStatus(Struct, frozen=True):
    provider: str
    installed: bool
    packages: list[str]
    imports: list[str]
    missing_imports: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "installed": self.installed,
            "packages": self.packages,
            "imports": self.imports,
            "missing_imports": self.missing_imports,
        }


def available_dependency_providers() -> list[str]:
    """Return Provider names that are allowed for dependency operations."""

    return sorted(OPTIONAL_PROVIDER_DEPENDENCIES)


def normalize_providers(providers: Iterable[str] | None = None) -> list[str]:
    """Validate and normalize user-provided Provider names.

    Passing ``None`` means all known optional providers. Empty strings are
    ignored so frontends can pass optional embedding Provider fields directly.
    """

    if providers is None:
        return available_dependency_providers()

    normalized: list[str] = []
    unknown: list[str] = []
    for provider in providers:
        name = str(provider).strip().lower()
        if not name:
            continue
        if name not in OPTIONAL_PROVIDER_DEPENDENCIES:
            unknown.append(name)
            continue
        if name not in normalized:
            normalized.append(name)

    if unknown:
        raise DependencyError(
            f"Unsupported provider dependency request: {', '.join(unknown)}",
            code="unsupported_provider_dependency",
            details={
                "providers": unknown,
                "allowed_providers": available_dependency_providers(),
            },
            recoverable=True,
        )

    return normalized


def provider_status(provider: str) -> ProviderDependencyStatus:
    """Return dependency status for a single whitelisted Provider."""

    providers = normalize_providers([provider])
    if not providers:
        raise DependencyError(
            "Provider name is required",
            code="missing_provider",
            recoverable=True,
        )
    name = providers[0]
    imports = PROVIDER_IMPORTS[name]
    missing = [module for module in imports if importlib.util.find_spec(module) is None]
    return ProviderDependencyStatus(
        provider=name,
        installed=not missing,
        packages=list(OPTIONAL_PROVIDER_DEPENDENCIES[name]),
        imports=list(imports),
        missing_imports=missing,
    )


def dependency_status(providers: Iterable[str] | None = None) -> dict[str, Any]:
    """Return install status for requested Provider dependencies."""

    requested = normalize_providers(providers)
    statuses = {provider: provider_status(provider).to_dict() for provider in requested}
    return {
        "providers": statuses,
        "allowed_providers": available_dependency_providers(),
    }


def packages_for_providers(providers: Iterable[str]) -> list[str]:
    """Return de-duplicated pip requirement strings for whitelisted providers."""

    packages: list[str] = []
    for provider in normalize_providers(providers):
        for package in OPTIONAL_PROVIDER_DEPENDENCIES[provider]:
            if package not in packages:
                packages.append(package)
    return packages


def install_dependencies(
    providers: Iterable[str],
    *,
    scope: InstallScope = "current_runtime",
    timeout: int = 600,
) -> dict[str, Any]:
    """Install missing optional Provider dependencies into the current runtime.

    The only supported scope is ``current_runtime``. Installation is executed via
    ``sys.executable -m pip install`` without shell expansion.
    """

    if scope != "current_runtime":
        raise DependencyError(
            f"Unsupported dependency installation scope: {scope}",
            code="unsupported_dependency_scope",
            details={"scope": scope, "allowed_scopes": ["current_runtime"]},
            recoverable=True,
        )

    requested = normalize_providers(providers)
    if not requested:
        return {
            "ok": True,
            "providers": [],
            "packages": [],
            "already_installed": True,
            "stdout": "",
            "stderr": "",
        }

    before = dependency_status(requested)
    missing_providers = [
        provider
        for provider, status in before["providers"].items()
        if not status.get("installed", False)
    ]
    packages = packages_for_providers(missing_providers)
    if not packages:
        return {
            "ok": True,
            "providers": requested,
            "packages": [],
            "already_installed": True,
            "before": before,
            "after": before,
            "stdout": "",
            "stderr": "",
        }

    command = [sys.executable, "-m", "pip", "install", *packages]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise DependencyError(
            "Current Python executable was not found while installing dependencies",
            code="python_executable_not_found",
            details={"executable": sys.executable},
            recoverable=True,
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise DependencyError(
            "Dependency installation timed out",
            code="dependency_install_timeout",
            details={"timeout": timeout, "packages": packages},
            recoverable=True,
        ) from exc

    after = dependency_status(requested)
    stdout = _summarize_output(completed.stdout)
    stderr = _summarize_output(completed.stderr)
    ok = completed.returncode == 0 and all(
        status.get("installed", False) for status in after["providers"].values()
    )
    if not ok:
        raise DependencyError(
            "Dependency installation failed",
            code="dependency_install_failed",
            details={
                "returncode": completed.returncode,
                "providers": requested,
                "packages": packages,
                "stdout": stdout,
                "stderr": stderr,
                "before": before,
                "after": after,
            },
            recoverable=True,
        )

    return {
        "ok": True,
        "providers": requested,
        "packages": packages,
        "already_installed": False,
        "returncode": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "before": before,
        "after": after,
    }


def _summarize_output(value: str, *, max_chars: int = 4000) -> str:
    value = value.strip()
    if len(value) <= max_chars:
        return value
    return value[-max_chars:]
