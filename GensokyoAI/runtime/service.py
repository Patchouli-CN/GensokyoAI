"""Frontend-agnostic runtime service for GensokyoAI.

This module is the public backend boundary for local clients, desktop apps,
web adapters, CLIs, and third-party frontends. It intentionally contains no
Flutter-specific behavior. Clients should interact with it through a stable RPC
transport such as ``bridge_main.py`` or a future HTTP/WebSocket adapter.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import yaml
from msgspec import Struct

from GensokyoAI.core.agent import Agent
from GensokyoAI.core.agent.model_registry import ModelRegistryService
from GensokyoAI.core.agent.types import ModelInfo
from GensokyoAI.core.character_package import CharacterPackageService
from GensokyoAI.core.character_validator import CharacterValidator
from GensokyoAI.core.config import ConfigLoader
from GensokyoAI.core.config_validator import ConfigDiagnostic, ConfigValidator
from GensokyoAI.core.events import Event, SystemEvent
from GensokyoAI.core.migrations import migration_diagnostics_summary
from GensokyoAI.core.schema_versions import (
    CONFIG_SCHEMA_VERSION,
    MEMORY_SCHEMA_VERSION,
    SESSION_EXPORT_FORMAT,
    SESSION_EXPORT_SCHEMA_VERSION,
    SESSION_SCHEMA_VERSION,
    schema_versions_payload,
)
from GensokyoAI.core.version import package_version
from GensokyoAI.runtime.dependencies import InstallScope, dependency_status, install_dependencies
from GensokyoAI.runtime.resource_control import (
    ResourceGate,
    ResourceLimitError,
    build_resource_gates,
    resource_limit_payload,
    resource_scope,
)
from GensokyoAI.runtime.rpc import (
    RpcError,
    dispatch_rpc,
    legacy_rpc_methods,
    rpc_method_specs,
    rpc_methods,
    runtime_error_to_dict,
    runtime_protocol_metadata,
)
from GensokyoAI.session.context import SessionContext
from GensokyoAI.tools.external_manager import ExternalToolManager
from GensokyoAI.utils.helpers import utc_now

RUNTIME_EVENT_BACKPRESSURE_DROPPED = "runtime.backpressure.dropped"
RUNTIME_DEPRECATED_FIELDS: tuple[dict[str, str | None], ...] = ()
RUNTIME_COMPATIBILITY_NOTES: tuple[dict[str, str], ...] = (
    {
        "scope": "runtime.rpc.legacy_methods",
        "status": "deprecated",
        "message": "Legacy non-namespaced RPC methods remain available for compatibility; new clients should use namespaced methods from runtime.info.methods.",
        "replacement": "Use runtime.info.method_specs to map legacy methods to namespaced replacements.",
    },
)
REDACTED_VALUE = "[redacted]"
SENSITIVE_EVENT_FIELD_NAMES = {
    "api_key",
    "apikey",
    "api-key",
    "authorization",
    "auth",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "client_secret",
    "password",
    "passwd",
    "headers",
    "extra_headers",
}


class RuntimeState(Struct):
    """Mutable state owned by a single runtime service instance."""

    root_dir: Path
    config_path: Path | None = None
    character_path: Path | None = None
    agent: Agent | None = None
    started: bool = False


def runtime_deprecated_fields() -> list[dict[str, str | None]]:
    """Return Runtime public field deprecation metadata."""

    return [dict(item) for item in RUNTIME_DEPRECATED_FIELDS]


def runtime_compatibility_notes() -> list[dict[str, str]]:
    """Return Runtime compatibility notes for clients and release docs."""

    return [dict(item) for item in RUNTIME_COMPATIBILITY_NOTES]


class RuntimeService:
    """Frontend-agnostic facade around :class:`GensokyoAI.core.agent.Agent`.

    The service accepts plain JSON-compatible parameters and returns plain
    JSON-compatible payloads. It must not depend on a concrete frontend or UI
    toolkit. The current Flutter client is only one caller of this API.
    """

    def __init__(self, root_dir: Path | None = None) -> None:
        self.state = RuntimeState(root_dir=(root_dir or Path.cwd()).resolve())
        self._lock = asyncio.Lock()
        self._model_registry = ModelRegistryService()
        self.external_tool_manager = ExternalToolManager()
        self._runtime_event_subscriptions: dict[str, list[str]] = {}
        self._config_validator = ConfigValidator()
        self._character_validator = CharacterValidator()
        self._character_package_service = CharacterPackageService()
        self._resource_gates = self._build_resource_gates()

    async def handle(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        structured_errors: bool = True,
    ) -> Any:
        return await dispatch_rpc(self, method, params, structured_errors=structured_errors)

    async def health(self) -> dict[str, Any]:
        """Return a lightweight runtime health payload."""

        return {
            "ok": True,
            "root_dir": str(self.state.root_dir),
            "initialized": self.state.agent is not None,
            "started": self.state.started,
        }

    async def info(self) -> dict[str, Any]:
        """Return runtime capability information for generic clients."""

        protocol_metadata = runtime_protocol_metadata()
        return {
            "name": "GensokyoAI Runtime",
            "package_version": package_version(self.state.root_dir),
            "protocol": "json-lines-rpc",
            **protocol_metadata,
            "capabilities": [
                "agent.lifecycle",
                "agent.messaging",
                "agent.streaming",
                "character.discovery",
                "character.validation",
                "character_package.management",
                "dependency.management",
                "external_tool.status",
                "memory.management",
                "memory.search",
                "memory.graph",
                "model.discovery",
                "config.validation",
                "migration.diagnostics",
                "resource_control.runtime_gates",
                "runtime.events",
                "runtime.health",
                "runtime.versioning",
                "session.management",
                "initiative_timer.management",
            ],
            "methods": rpc_methods(),
            "legacy_methods": legacy_rpc_methods(),
            "method_specs": rpc_method_specs(),
            "schema_versions": schema_versions_payload(),
            "config_schema_version": CONFIG_SCHEMA_VERSION,
            "deprecated_fields": runtime_deprecated_fields(),
            "compatibility_notes": runtime_compatibility_notes(),
            "migration_diagnostics": migration_diagnostics_summary(),
            "external_tools": self.external_tool_manager.source_status(include_tools=False),
            "resource_control": self._resource_control_payload(),
        }

    async def validate_config(
        self,
        config_path: str | None = None,
        config: dict[str, Any] | None = None,
        model_overrides: dict[str, Any] | None = None,
        embedding_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return structured configuration diagnostics without initializing Agent."""

        loader = ConfigLoader()
        diagnostics: list[ConfigDiagnostic] = []
        resolved_config_path = None
        if config is not None:
            diagnostics.extend(loader.validate_dict(config))
        else:
            resolved_config_path = (
                self._resolve_optional(config_path)
                or self.state.config_path
                or self.state.root_dir / "config" / "default.yaml"
            )
            with open(resolved_config_path, encoding="utf-8") as file:
                config_data = yaml.safe_load(file) or {}
            diagnostics.extend(loader.validate_dict(config_data))

        if model_overrides:
            diagnostics.extend(self._config_validator.validate_model_overrides(model_overrides))
        if embedding_overrides:
            diagnostics.extend(
                self._config_validator.validate_embedding_overrides(embedding_overrides)
            )

        return self._config_validation_payload(
            diagnostics,
            config_path=resolved_config_path,
            source="inline" if config is not None else "file",
        )

    async def validate_character(
        self,
        character_path: str | None = None,
        character: str | None = None,
        character_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return structured character YAML diagnostics and preview."""

        resolved_character_path: Path | None = None
        source = "inline" if character_data is not None else "file"
        if character_data is None:
            resolved_character_path = self._resolve_character(
                character_path=character_path,
                character=character,
            )
            if resolved_character_path is None:
                raise ValueError("Character path or inline character_data is required")
            with open(resolved_character_path, encoding="utf-8") as file:
                character_data = yaml.safe_load(file) or {}

        diagnostics = self._character_validator.validate_character_dict(character_data)
        preview = self._character_validator.build_preview(
            character_data,
            fallback_id=resolved_character_path.stem if resolved_character_path else None,
        )
        return self._character_validation_payload(
            diagnostics,
            character_path=resolved_character_path,
            source=source,
            preview=preview,
        )

    async def validate_character_package(self, package_path: str) -> dict[str, Any]:
        """Return structured diagnostics for a .gensokyo-character package."""

        resolved_package_path = self._resolve_sandboxed_path(package_path)
        return self._character_package_service.validate_package(resolved_package_path)

    async def preview_character_package(self, package_path: str) -> dict[str, Any]:
        """Return manifest and character preview for a .gensokyo-character package."""

        resolved_package_path = self._resolve_sandboxed_path(package_path)
        return self._character_package_service.preview_package(resolved_package_path)

    async def import_character_package(
        self,
        package_path: str,
        locale: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Import a .gensokyo-character package into the Runtime characters directory."""

        resolved_package_path = self._resolve_sandboxed_path(package_path)
        return self._character_package_service.import_package(
            resolved_package_path,
            self.state.root_dir / "characters",
            locale=locale,
            overwrite=overwrite,
        )

    async def export_character_package(
        self,
        character_path: str,
        output_path: str,
        package_id: str | None = None,
        author: str | None = None,
        license: str | None = None,
        assets: list[str] | None = None,
        overwrite: bool = False,
        source: str | None = None,
        author_url: str | None = None,
        license_url: str | None = None,
        license_detail: str | None = None,
        attribution: list[dict[str, Any]] | None = None,
        external_links: list[dict[str, Any]] | None = None,
        repository: dict[str, Any] | None = None,
        signature: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Export a character YAML file as a .gensokyo-character package."""

        resolved_character_path = self._resolve_sandboxed_path(character_path)
        resolved_output_path = self._resolve_sandboxed_path(output_path)
        resolved_assets = [self._resolve_sandboxed_path(asset) for asset in assets or []]
        return self._character_package_service.export_package(
            resolved_character_path,
            resolved_output_path,
            package_id=package_id,
            author=author,
            license=license,
            assets=resolved_assets,
            overwrite=overwrite,
            source=source,
            author_url=author_url,
            license_url=license_url,
            license_detail=license_detail,
            attribution=attribution,
            external_links=external_links,
            repository=repository,
            signature=signature,
        )

    async def init(
        self,
        config_path: str | None = None,
        character_path: str | None = None,
        character: str | None = None,
        session_id: str | None = None,
        new_session: bool = False,
        start: bool = True,
        model_overrides: dict[str, Any] | None = None,
        embedding_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Initialize the Agent and prepare a session.

        A current session must exist before ``Agent.start()`` because the semantic
        memory and think engine are session-scoped.
        """
        async with self._lock:
            if self.state.agent is not None:
                await self._shutdown_locked()

            config_file = (
                self._resolve_optional(config_path)
                or self.state.root_dir / "config" / "default.yaml"
            )
            char_file = self._resolve_character(
                character_path=character_path,
                character=character,
            )

            loader = ConfigLoader()
            config = loader.load(config_file)
            self._apply_model_overrides(config.model, model_overrides)
            self._apply_embedding_overrides(config.embedding, embedding_overrides)
            agent = Agent(config=config, config_file=config_file, character_file=char_file)

            if session_id:
                if not agent.resume_session(session_id):
                    raise ValueError(f"Session does not exist: {session_id}")
            elif new_session or not agent.session_manager.list_sessions():
                agent.create_session()
            else:
                sessions = agent.session_manager.list_sessions()
                latest = max(sessions, key=lambda item: item.last_active)
                agent.session_manager.set_current_session(latest.session_id)

            if start:
                await agent.start()
                self.state.started = True

            self.state.agent = agent
            self.state.config_path = config_file
            self.state.character_path = char_file
            self._resource_gates = agent.runtime_context.resource_gates
            agent.runtime_context.model_client.update_resource_gates(self._resource_gates)
            agent.runtime_context.tool_executor.update_resource_gates(self._resource_gates)

            current = agent.session_manager.get_current_session()
            character_name = agent.config.character.name if agent.config.character else None
            return {
                "character": self._character_payload(char_file, character_name),
                "session": self._session_payload(current) if current else None,
                "started": self.state.started,
            }

    async def list_characters(self, locale: str | None = None) -> list[dict[str, Any]]:
        characters_dir = self.state.root_dir / "characters"
        search_dirs = []
        if locale:
            search_dirs.append(characters_dir / locale)
        search_dirs.append(characters_dir)
        if characters_dir.exists():
            search_dirs.extend(path for path in characters_dir.iterdir() if path.is_dir())

        seen: set[Path] = set()
        characters: list[dict[str, Any]] = []
        for directory in search_dirs:
            if not directory.exists():
                continue
            for path in sorted([*directory.glob("*.yaml"), *directory.glob("*.yml")]):
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                try:
                    with open(path, encoding="utf-8") as file:
                        data = yaml.safe_load(file) or {}
                    diagnostics = self._character_validator.validate_character_dict(data)
                    preview = (
                        self._character_validator.build_preview(data, fallback_id=path.stem) or {}
                    )
                    characters.append(
                        {
                            "id": path.stem,
                            "name": preview.get("name") or path.stem,
                            "path": str(path.relative_to(self.state.root_dir)),
                            "greeting": data.get("greeting", "") if isinstance(data, dict) else "",
                            "metadata": preview.get("metadata", {}),
                            "preview": preview,
                            "diagnostics": [item.to_dict() for item in diagnostics],
                            "ok": not any(item.severity == "error" for item in diagnostics),
                        }
                    )
                except yaml.YAMLError as exc:  # keep listing robust for broken user files
                    diagnostic = ConfigDiagnostic(
                        code="character.yaml.invalid",
                        path="$",
                        severity="error",
                        message=f"Character YAML is invalid: {exc}",
                        suggestion="请检查 YAML 缩进、冒号和列表格式。",
                    )
                    characters.append(
                        {
                            "id": path.stem,
                            "name": path.stem,
                            "path": str(path.relative_to(self.state.root_dir)),
                            "error": str(exc),
                            "diagnostics": [diagnostic.to_dict()],
                            "ok": False,
                        }
                    )
                except Exception as exc:  # keep listing robust for broken user files
                    diagnostic = ConfigDiagnostic(
                        code="character.load.failed",
                        path="$",
                        severity="error",
                        message=str(exc),
                        suggestion="请确认角色文件可读取且格式正确。",
                    )
                    characters.append(
                        {
                            "id": path.stem,
                            "name": path.stem,
                            "path": str(path.relative_to(self.state.root_dir)),
                            "error": str(exc),
                            "diagnostics": [diagnostic.to_dict()],
                            "ok": False,
                        }
                    )
        return characters

    async def list_models(
        self,
        refresh: bool = False,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return current runtime model metadata through ModelRegistryService."""
        agent = self._require_agent()
        config = agent.config.model
        models = await self._model_registry.list_models(
            config,
            refresh=refresh,
            overrides=overrides,
        )
        return {
            "provider": config.provider,
            "model": config.name,
            "models": [self._model_payload(model) for model in models],
        }

    async def model_info(
        self,
        model_id: str | None = None,
        refresh: bool = False,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return metadata for one model in the current runtime provider."""
        agent = self._require_agent()
        config = agent.config.model
        model = await self._model_registry.get_model_info(
            config,
            model_id=model_id,
            refresh=refresh,
            overrides=overrides,
        )
        return {
            "provider": config.provider,
            "requested_model": model_id or config.name,
            "model": self._model_payload(model),
        }

    async def create_session(self) -> dict[str, Any]:
        agent = self._require_agent()
        async with self._lock:
            session = agent.create_session()
            return self._session_payload(session)

    async def list_sessions(self) -> list[dict[str, Any]]:
        agent = self._require_agent()
        return [self._session_payload(session) for session in agent.session_manager.list_sessions()]

    async def current_session(self) -> dict[str, Any] | None:
        agent = self._require_agent()
        session = agent.session_manager.get_current_session()
        return self._session_payload(session) if session else None

    async def resume_session(self, session_id: str) -> dict[str, Any]:
        agent = self._require_agent()
        async with self._lock:
            if not agent.resume_session(session_id):
                raise ValueError(f"Session does not exist: {session_id}")
            session = agent.session_manager.get_current_session()
            return self._session_payload(session) if session else {}

    async def delete_session(self, session_id: str) -> dict[str, Any]:
        if not session_id:
            raise ValueError("Session id is required")

        agent = self._require_agent()
        async with self._lock:
            current = agent.session_manager.get_current_session()
            was_current = bool(current and current.session_id == session_id)
            deleted = agent.session_manager.delete_session(session_id)
            if not deleted:
                raise ValueError(f"Session does not exist: {session_id}")
            next_current = agent.session_manager.get_current_session()
            remaining_sessions = [
                self._session_payload(session) for session in agent.session_manager.list_sessions()
            ]
            return {
                "deleted": True,
                "session_id": session_id,
                "was_current": was_current,
                "current_session": self._session_payload(next_current) if next_current else None,
                "remaining_count": len(remaining_sessions),
                "remaining_sessions": remaining_sessions,
            }

    async def export_session(self, session_id: str | None = None) -> dict[str, Any]:
        agent = self._require_agent()
        manager = agent.session_manager
        current = manager.get_current_session()
        target_session_id = session_id or (current.session_id if current else None)
        if not target_session_id:
            raise ValueError("No active session to export")

        if current and current.session_id == target_session_id:
            manager.save_current()

        session = manager.get_session(target_session_id)
        if session is None:
            raise ValueError(f"Session does not exist: {target_session_id}")

        messages = manager.persistence.load_messages(target_session_id)
        is_current = bool(current and current.session_id == target_session_id)
        character_name = agent.config.character.name if agent.config.character else None
        return {
            "format": SESSION_EXPORT_FORMAT,
            "version": SESSION_EXPORT_SCHEMA_VERSION,
            "schema_version": SESSION_EXPORT_SCHEMA_VERSION,
            "session_schema_version": SESSION_SCHEMA_VERSION,
            "memory_schema_version": MEMORY_SCHEMA_VERSION,
            "exported_at": utc_now().isoformat(),
            "is_current": is_current,
            "character": self._character_payload(self.state.character_path, character_name),
            "session": self._session_payload(session),
            "messages": messages,
            "message_count": len(messages),
            "runtime": {
                "root_dir": str(self.state.root_dir),
                "config_path": str(self.state.config_path) if self.state.config_path else None,
                "character_path": (
                    str(self.state.character_path) if self.state.character_path else None
                ),
                "started": self.state.started,
            },
        }

    async def rename_session(
        self,
        title: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        normalized_title = title.strip()
        if not normalized_title:
            raise ValueError("Session title is required")

        agent = self._require_agent()
        manager = agent.session_manager
        current = manager.get_current_session()
        target_session_id = session_id or (current.session_id if current else None)
        if not target_session_id:
            raise ValueError("No active session to rename")

        async with self._lock:
            session = manager.get_session(target_session_id)
            if session is None:
                raise ValueError(f"Session does not exist: {target_session_id}")
            session.metadata["title"] = normalized_title
            session.touch()
            manager.persistence.save_session(session)
            return self._session_payload(session)

    async def session_messages(self, session_id: str | None = None) -> dict[str, Any]:
        """Return complete editable messages for one session."""
        agent = self._require_agent()
        manager = agent.session_manager
        current = manager.get_current_session()
        target_session_id = session_id or (current.session_id if current else None)
        if not target_session_id:
            raise ValueError("No active session to read messages")

        session = manager.get_session(target_session_id)
        if session is None:
            raise ValueError(f"Session does not exist: {target_session_id}")

        messages = manager.persistence.load_messages(target_session_id)
        return self._session_messages_payload(manager, session, messages)

    async def session_replace_messages(
        self,
        messages: list[dict[str, Any]],
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Replace all messages in a session after frontend-side edits."""
        agent = self._require_agent()
        manager = agent.session_manager
        current = manager.get_current_session()
        target_session_id = session_id or (current.session_id if current else None)
        if not target_session_id:
            raise ValueError("No active session to replace messages")

        session = manager.get_session(target_session_id)
        if session is None:
            raise ValueError(f"Session does not exist: {target_session_id}")

        normalized_messages = self._normalize_session_messages(messages)
        async with self._lock:
            if not manager.replace_messages(target_session_id, normalized_messages):
                raise ValueError(f"Session does not exist: {target_session_id}")
            updated_session = manager.get_session(target_session_id) or session
            updated_messages = manager.persistence.load_messages(target_session_id)
            return {
                "replaced": True,
                **self._session_messages_payload(manager, updated_session, updated_messages),
            }

    async def session_regenerate_from(
        self,
        message_index: int,
        session_id: str | None = None,
        system_contexts: list[str] | None = None,
    ) -> dict[str, Any]:
        """Truncate from a historical user message and regenerate following assistant reply."""
        if message_index < 0:
            raise ValueError("Message index must be greater than or equal to 0")

        async with (
            self._resource_scope("runtime", "agent_message"),
            self._resource_scope("agent_message", "agent_message"),
        ):
            agent = await self._ensure_started()
            manager = agent.session_manager
            current = manager.get_current_session()
            target_session_id = session_id or (current.session_id if current else None)
            if not target_session_id:
                raise ValueError("No active session to regenerate messages")

            session = manager.get_session(target_session_id)
            if session is None:
                raise ValueError(f"Session does not exist: {target_session_id}")

            original_messages = manager.persistence.load_messages(target_session_id)
            if message_index >= len(original_messages):
                raise ValueError("Message index is out of range")

            user_index = self._find_regeneration_user_index(original_messages, message_index)
            if user_index is None:
                raise ValueError("No user message found at or before message_index")

            user_message = original_messages[user_index]
            user_content = user_message.get("content")
            if not isinstance(user_content, str) or not user_content:
                raise ValueError("Regeneration target user message content is required")

            previous_session_id = current.session_id if current else None
            async with self._lock:
                self._activate_session_for_regeneration(agent, target_session_id)
                manager.replace_messages(target_session_id, original_messages[:user_index])

            try:
                response = await agent.send(user_content, system_contexts)
                content = response.content if response else ""
            finally:
                if previous_session_id and previous_session_id != target_session_id:
                    self._activate_session_for_regeneration(agent, previous_session_id)

            updated_session = manager.get_session(target_session_id) or session
            updated_messages = manager.persistence.load_messages(target_session_id)
            return {
                "regenerated": True,
                "from_index": message_index,
                "user_message_index": user_index,
                "role": "assistant",
                "content": content,
                **self._session_messages_payload(manager, updated_session, updated_messages),
            }

    async def rollback_session(
        self,
        num: int = 1,
        mode: str = "turns",
    ) -> dict[str, Any]:
        if num < 1:
            raise ValueError("Rollback num must be greater than or equal to 1")
        if mode not in {"turns", "messages"}:
            raise ValueError("Rollback mode must be either 'turns' or 'messages'")

        agent = self._require_agent()
        async with self._lock:
            session = agent.session_manager.get_current_session()
            if session is None:
                raise ValueError("No active session to rollback")
            before_messages = agent.session_manager.get_working_memory().get_context()
            before_total_turns = session.total_turns
            agent.rollback(num=num, mode=mode)  # type: ignore[arg-type]
            agent.session_manager.save_current()
            after_session = agent.session_manager.get_current_session()
            after_messages = agent.session_manager.persistence.load_messages(session.session_id)
            return {
                "rolled_back": True,
                "num": num,
                "mode": mode,
                "before_total_turns": before_total_turns,
                "after_total_turns": after_session.total_turns if after_session else 0,
                "before_message_count": len(before_messages),
                "after_message_count": len(after_messages),
                "message_count": len(after_messages),
                "session": self._session_payload(after_session) if after_session else None,
            }

    async def send_message(
        self,
        message: str,
        system_contexts: list[str] | None = None,
    ) -> dict[str, Any]:
        async with (
            self._resource_scope("runtime", "agent_message"),
            self._resource_scope("agent_message", "agent_message"),
        ):
            agent = await self._ensure_started()
            response = await agent.send(message, system_contexts)
            content = response.content if response else ""
            session = agent.session_manager.get_current_session()
            return {
                "role": "assistant",
                "content": content,
                "session": self._session_payload(session) if session else None,
                "initiative_timer": self._agent_initiative_timer_payload(agent),
            }

    async def iter_message_stream(
        self,
        message: str,
        system_contexts: list[str] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield Runtime stream events as soon as Agent stream chunks are produced."""

        async with (
            self._resource_scope("runtime", "agent_stream"),
            self._resource_scope("agent_message", "agent_stream"),
            self._resource_scope("stream", "agent_stream"),
        ):
            async for event in self._iter_message_stream_locked(message, system_contexts):
                yield event

    async def _iter_message_stream_locked(
        self,
        message: str,
        system_contexts: list[str] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        agent = await self._ensure_started()
        full_content = ""
        index = 0

        try:
            async for chunk in agent.send_stream(message, system_contexts):
                event = self._stream_chunk_payload(chunk, index)
                if event.get("type") == "content":
                    full_content += event.get("content", "")
                yield event
                index += 1
        except asyncio.CancelledError:
            yield {
                "type": "cancelled",
                "index": index,
                "content": full_content,
            }
            raise
        except Exception as error:
            yield {
                "type": "error",
                "index": index,
                "content": full_content,
                "error": runtime_error_to_dict(error),
            }
            raise

        session = agent.session_manager.get_current_session()
        yield {
            "type": "finish",
            "index": index,
            "content": full_content,
            "session": self._session_payload(session) if session else None,
            "initiative_timer": self._agent_initiative_timer_payload(agent),
        }

    async def send_message_stream(
        self,
        message: str,
        system_contexts: list[str] | None = None,
    ) -> dict[str, Any]:
        events: list[dict[str, Any]] = []

        async for event in self.iter_message_stream(message, system_contexts):
            events.append(event)

        finish_event = events[-1] if events else {}
        session_payload = finish_event.get("session")
        return {
            "role": "assistant",
            "content": finish_event.get("content", ""),
            "events": events,
            "session": session_payload,
        }

    async def initiative_timer_current(self) -> dict[str, Any] | None:
        agent = self._require_agent()
        return agent.current_initiative_timer()

    async def initiative_timer_update(
        self,
        timer_id: str | None = None,
        delay_seconds: int | float | None = None,
        due_at: str | None = None,
        pending_summary: str | None = None,
    ) -> dict[str, Any]:
        agent = self._require_agent()
        return await agent.update_initiative_timer(
            timer_id=timer_id,
            delay_seconds=delay_seconds,
            due_at=due_at,
            pending_summary=pending_summary,
        )

    async def initiative_timer_cancel(
        self,
        timer_id: str | None = None,
        reason: str = "cancelled",
    ) -> dict[str, Any]:
        agent = self._require_agent()
        return await agent.cancel_initiative_timer(timer_id=timer_id, reason=reason)

    async def initiative_timer_trigger(self, timer_id: str | None = None) -> dict[str, Any]:
        agent = self._require_agent()
        return await agent.trigger_initiative_timer(timer_id=timer_id)

    async def initiative_timer_hesitation(self) -> dict[str, Any]:
        agent = self._require_agent()
        status = getattr(agent, "initiative_hesitation_status", None)
        if not callable(status):
            raise RuntimeError("Current agent does not support initiative hesitation status")
        payload = status()
        return payload if isinstance(payload, dict) else {}

    async def initiative_timer_hesitation_set(
        self,
        enabled: bool,
        persist: bool = True,
    ) -> dict[str, Any]:
        agent = self._require_agent()
        setter = getattr(agent, "set_initiative_hesitation_enabled", None)
        if not callable(setter):
            raise RuntimeError("Current agent does not support initiative hesitation control")
        payload = setter(bool(enabled), persist=persist)
        return payload if isinstance(payload, dict) else {}

    async def dependency_status(self, providers: list[str] | None = None) -> dict[str, Any]:
        """Return optional Provider dependency status for generic clients."""

        return dependency_status(providers)

    async def install_dependencies(
        self,
        providers: list[str],
        scope: InstallScope = "current_runtime",
        timeout: int = 600,
    ) -> dict[str, Any]:
        """Install whitelisted optional Provider dependencies."""

        async with (
            self._resource_scope("runtime", "dependency_install"),
            self._resource_scope("dependency_install", "dependency_install"),
        ):
            configured_timeout = self._resource_control_config().dependency_install_timeout_seconds
            effective_timeout = configured_timeout if timeout == 600 else timeout
            return install_dependencies(providers, scope=scope, timeout=effective_timeout)

    async def external_tool_status(self, include_tools: bool = True) -> dict[str, Any]:
        """Return external tool source status without exposing transport details."""

        return self.external_tool_manager.source_status(include_tools=include_tools)

    async def memory_list(
        self,
        topic_id: str | None = None,
        topic_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List current-session semantic memories with topic diagnostics."""

        memory = self._require_semantic_memory()
        return memory.list_memories(
            topic_id=topic_id,
            topic_name=topic_name,
            limit=max(1, min(limit, 200)),
            offset=max(0, offset),
        )

    async def memory_search(
        self,
        query: str,
        top_k: int | None = None,
        threshold: float | None = None,
        include_embedding: bool = True,
    ) -> dict[str, Any]:
        """Search current-session semantic memories with explainable diagnostics."""

        if not query or not query.strip():
            raise ValueError("Memory search query is required")
        memory = self._require_semantic_memory()
        items = await memory.search_async(
            query=query,
            top_k=top_k,
            threshold=threshold,
            include_embedding=include_embedding,
        )
        diagnostics = (
            items[0].get("diagnostics", {})
            if items
            else {
                "embedding_requested": include_embedding,
                "embedding_used": False,
                "threshold": threshold,
            }
        )
        return {
            "query": query,
            "items": items,
            "count": len(items),
            "diagnostics": diagnostics,
        }

    async def memory_get(self, memory_id: str) -> dict[str, Any]:
        """Return one semantic memory by id."""

        if not memory_id:
            raise ValueError("Memory id is required")
        memory = self._require_semantic_memory()
        item = memory.get_memory(memory_id)
        if item is None:
            raise ValueError(f"Memory does not exist: {memory_id}")
        return item

    async def memory_update(
        self,
        memory_id: str,
        content: str | None = None,
        importance: float | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Update one semantic memory by id."""

        if not memory_id:
            raise ValueError("Memory id is required")
        memory = self._require_semantic_memory()
        item = await memory.update_memory(
            memory_id,
            content=content,
            importance=importance,
            tags=tags,
        )
        if item is None:
            raise ValueError(f"Memory does not exist: {memory_id}")
        return {"updated": True, "memory": item}

    async def memory_delete(self, memory_id: str) -> dict[str, Any]:
        """Delete one semantic memory by id."""

        if not memory_id:
            raise ValueError("Memory id is required")
        memory = self._require_semantic_memory()
        deleted = await memory.delete_memory(memory_id)
        if not deleted:
            raise ValueError(f"Memory does not exist: {memory_id}")
        return {"deleted": True, "memory_id": memory_id}

    async def memory_graph(self) -> dict[str, Any]:
        """Return current-session topic graph for memory visualization."""

        memory = self._require_semantic_memory()
        graph = memory.get_topic_graph()
        return {
            **graph,
            "topic_count": len(graph.get("nodes", [])),
            "edge_count": len(graph.get("edges", [])),
        }

    async def create_event_subscription(
        self,
        event_types: list[str] | None = None,
        categories: list[str] | None = None,
        queue_size: int = 100,
    ) -> dict[str, Any]:
        """Create an EventBus-backed Runtime event subscription."""

        agent = self._require_agent()
        resolved_events = self._resolve_runtime_event_types(event_types, categories)
        if queue_size < 1:
            raise ValueError("Subscription queue_size must be greater than or equal to 1")

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=queue_size)
        subscription_ids: list[str] = []
        dropped_count = 0

        async def enqueue_event(event: Event) -> None:
            nonlocal dropped_count
            payload = self._runtime_event_payload(event)
            if queue.full():
                dropped_count += 1
                try:
                    queue.get_nowait()
                    queue.task_done()
                except asyncio.QueueEmpty:
                    pass
                payload = self._runtime_backpressure_payload(
                    dropped_count=dropped_count,
                    dropped_event=payload,
                    queue_size=queue_size,
                )
                if queue.full():
                    try:
                        queue.get_nowait()
                        queue.task_done()
                    except asyncio.QueueEmpty:
                        pass
            queue.put_nowait(payload)

        for event_type in resolved_events:
            subscription_ids.append(agent.event_bus.subscribe(event_type, enqueue_event))

        subscription_id = ",".join(subscription_ids)
        self._runtime_event_subscriptions[subscription_id] = subscription_ids
        return {
            "subscription_id": subscription_id,
            "event_types": [event_type.value for event_type in resolved_events],
            "queue": queue,
            "queue_size": queue_size,
        }

    async def close_event_subscription(self, subscription_id: str) -> dict[str, Any]:
        """Close a previously created Runtime event subscription."""

        agent = self._require_agent()
        subscription_ids = self._runtime_event_subscriptions.pop(subscription_id, None)
        if subscription_ids is None:
            raise ValueError(f"Runtime event subscription does not exist: {subscription_id}")

        removed = 0
        for event_bus_subscription_id in subscription_ids:
            if agent.event_bus.unsubscribe(event_bus_subscription_id):
                removed += 1
        return {"subscription_id": subscription_id, "closed": True, "removed": removed}

    async def shutdown(self) -> dict[str, Any]:
        async with self._lock:
            await self._shutdown_locked()
        return {"ok": True}

    def _resource_control_config(self) -> Any:
        agent = self.state.agent
        if agent is not None and hasattr(agent, "config"):
            config = agent.config
            resource_control = getattr(config, "resource_control", None)
            if resource_control is not None:
                return resource_control
        return ConfigLoader().load().resource_control

    def _build_resource_gates(self, resource_control: Any | None = None) -> dict[str, ResourceGate]:
        config = resource_control or ConfigLoader().load().resource_control
        return build_resource_gates(config)

    def _resource_limit_rpc_error(self, error: ResourceLimitError) -> RpcError:
        payload = resource_limit_payload(error)
        return RpcError(
            payload["technical_message"],
            code=payload["code"],
            user_message=payload["user_message"],
            recoverable=payload["recoverable"],
            action_hint=payload["action_hint"],
            details=payload["details"],
        )

    @asynccontextmanager
    async def _resource_scope(self, gate_name: str, action: str) -> AsyncIterator[None]:
        try:
            async with resource_scope(self._resource_gates.get(gate_name), action):
                yield
        except ResourceLimitError as error:
            raise self._resource_limit_rpc_error(error) from error

    def _resource_control_payload(self) -> dict[str, Any]:
        config = self._resource_control_config()
        return {
            "enabled": bool(getattr(config, "enabled", True)),
            "categories": {
                "model": getattr(config, "model_max_concurrent", 2),
                "tool": getattr(config, "tool_max_concurrent", 2),
                "web_search": getattr(config, "web_search_max_concurrent", 1),
                "image_generation": getattr(config, "image_generation_max_concurrent", 1),
                "dependency_install": getattr(config, "dependency_install_max_concurrent", 1),
            },
            "provider_max_concurrent": getattr(config, "provider_max_concurrent", 2),
            "default_timeout_seconds": getattr(config, "default_timeout_seconds", 120.0),
            "dependency_install_timeout_seconds": getattr(
                config,
                "dependency_install_timeout_seconds",
                600,
            ),
            "gates": {name: gate.snapshot() for name, gate in self._resource_gates.items()},
        }

    async def _ensure_started(self) -> Agent:
        agent = self._require_agent()
        if not self.state.started:
            async with self._lock:
                if not self.state.started:
                    await agent.start()
                    self.state.started = True
        return agent

    async def _shutdown_locked(self) -> None:
        agent = self.state.agent
        if agent is not None:
            for subscription_id in list(self._runtime_event_subscriptions):
                try:
                    await self.close_event_subscription(subscription_id)
                except Exception:
                    self._runtime_event_subscriptions.pop(subscription_id, None)
            await agent.shutdown()
        self.state.agent = None
        self.state.started = False

    def _require_agent(self) -> Agent:
        if self.state.agent is None:
            raise RuntimeError("Runtime is not initialized. Call init first.")
        return self.state.agent

    def _require_semantic_memory(self) -> Any:
        agent = self._require_agent()
        try:
            return agent.semantic_memory
        except Exception as error:
            raise RuntimeError(
                "Semantic memory is not available for the current session"
            ) from error

    def _resolve_optional(self, value: str | None) -> Path | None:
        if not value:
            return None
        return self._resolve_sandboxed_path(value)

    def _resolve_sandboxed_path(self, value: str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = self.state.root_dir / path
        resolved = path.resolve()
        root = self.state.root_dir.resolve()
        if resolved != root and not resolved.is_relative_to(root):
            raise ValueError(f"Path is outside Runtime root directory: {value}")
        return resolved

    def _resolve_character(self, character_path: str | None, character: str | None) -> Path | None:
        if character_path:
            return self._resolve_optional(character_path)
        if not character:
            return None

        base = self.state.root_dir / "characters"
        candidates = [
            base / f"{character}.yaml",
            base / f"{character}.yml",
            base / "zh_cn" / f"{character}.yaml",
            base / "zh_cn" / f"{character}.yml",
            self.state.root_dir / character,
        ]
        for candidate in candidates:
            if candidate.exists():
                return self._resolve_sandboxed_path(str(candidate))
        raise FileNotFoundError(f"Character not found: {character}")

    def _character_payload(self, path: Path | None, name: str | None = None) -> dict[str, Any]:
        return {
            "id": path.stem if path else name,
            "name": name or (path.stem if path else "Unknown"),
            "path": (
                str(path.relative_to(self.state.root_dir))
                if path and path.is_relative_to(self.state.root_dir)
                else (str(path) if path else None)
            ),
        }

    @staticmethod
    def _apply_model_overrides(model: Any, overrides: dict[str, Any] | None) -> None:
        if not overrides:
            return
        validator = ConfigValidator()
        validator.raise_for_errors(validator.validate_model_overrides(overrides))
        RuntimeService._apply_overrides(model, overrides, ConfigValidator.MODEL_OVERRIDE_FIELDS)

    @staticmethod
    def _apply_embedding_overrides(embedding: Any, overrides: dict[str, Any] | None) -> None:
        if not overrides:
            return
        validator = ConfigValidator()
        validator.raise_for_errors(validator.validate_embedding_overrides(overrides))
        RuntimeService._apply_overrides(
            embedding,
            overrides,
            ConfigValidator.EMBEDDING_OVERRIDE_FIELDS,
        )

    @staticmethod
    def _apply_overrides(target: Any, overrides: dict[str, Any], allowed: set[str]) -> None:
        for key, value in overrides.items():
            if key not in allowed or value == "":
                continue
            setattr(target, key, value)

    def _character_validation_payload(
        self,
        diagnostics: list[ConfigDiagnostic],
        *,
        character_path: Path | None,
        source: str,
        preview: dict[str, Any] | None,
    ) -> dict[str, Any]:
        errors = [item for item in diagnostics if item.severity == "error"]
        warnings = [item for item in diagnostics if item.severity == "warning"]
        return {
            "ok": not errors,
            "source": source,
            "character_path": str(character_path) if character_path else None,
            "preview": preview,
            "diagnostics": [item.to_dict() for item in diagnostics],
            "error_count": len(errors),
            "warning_count": len(warnings),
        }

    def _config_validation_payload(
        self,
        diagnostics: list[ConfigDiagnostic],
        *,
        config_path: Path | None,
        source: str,
    ) -> dict[str, Any]:
        errors = [item for item in diagnostics if item.severity == "error"]
        warnings = [item for item in diagnostics if item.severity == "warning"]
        return {
            "ok": not errors,
            "source": source,
            "config_path": str(config_path) if config_path else None,
            "diagnostics": [item.to_dict() for item in diagnostics],
            "error_count": len(errors),
            "warning_count": len(warnings),
        }

    @staticmethod
    def _model_payload(model: ModelInfo) -> dict[str, Any]:
        return {
            "id": model.id,
            "name": model.name,
            "context_window": model.context_window,
            "capabilities": list(model.capabilities),
            "owned_by": model.owned_by,
            "metadata": dict(model.metadata),
        }

    @staticmethod
    def _stream_chunk_payload(chunk: Any, index: int) -> dict[str, Any]:
        chunk_type = getattr(chunk, "type", "text") or "text"
        event_type = "content" if chunk_type == "text" else chunk_type
        event: dict[str, Any] = {
            "type": event_type,
            "index": index,
            "content": getattr(chunk, "content", "") or "",
        }
        optional_fields = (
            "reasoning_content",
            "is_tool_call",
            "tool_info",
            "status",
            "error",
            "error_code",
            "error_details",
            "usage",
            "finish_reason",
        )
        for field_name in optional_fields:
            value = getattr(chunk, field_name, None)
            if value not in (None, False, "", [], {}):
                event[field_name] = value
        if getattr(chunk, "timing", None) is not None:
            event["timing"] = str(chunk.timing)
        references = getattr(chunk, "web_search_references", None)
        if references:
            event["web_search_references"] = [str(reference) for reference in references]
        diagnostics = getattr(chunk, "web_search_diagnostics", None)
        if diagnostics is not None:
            event["web_search_diagnostics"] = str(diagnostics)
        return event

    @staticmethod
    def _runtime_event_payload(event: Event) -> dict[str, Any]:
        return {
            "type": event.type.value,
            "id": event.id,
            "source": event.source,
            "data": RuntimeService._sanitize_runtime_event_value(event.data),
            "timestamp": event.timestamp.isoformat(),
            "metadata": RuntimeService._sanitize_runtime_event_value(event.metadata),
        }

    @staticmethod
    def _agent_initiative_timer_payload(agent: Any) -> dict[str, Any] | None:
        current = getattr(agent, "current_initiative_timer", None)
        status_getter = getattr(agent, "initiative_hesitation_status", None)
        status = status_getter() if callable(status_getter) else None
        status = status if isinstance(status, dict) else None
        if not callable(current):
            return {"timer": None, "hesitation": status} if status is not None else None
        payload = current()
        if isinstance(payload, dict):
            if status is not None and "hesitation_enabled" not in payload:
                return {**payload, "hesitation_enabled": status.get("enabled")}
            return payload
        return {"timer": None, "hesitation": status} if status is not None else None

    @staticmethod
    def _runtime_backpressure_payload(
        *,
        dropped_count: int,
        dropped_event: dict[str, Any],
        queue_size: int,
    ) -> dict[str, Any]:
        return {
            "type": RUNTIME_EVENT_BACKPRESSURE_DROPPED,
            "id": f"backpressure-{dropped_count}",
            "source": "runtime.service",
            "data": {
                "dropped_count": dropped_count,
                "queue_size": queue_size,
                "dropped_event_type": dropped_event.get("type"),
                "dropped_event_id": dropped_event.get("id"),
            },
            "timestamp": utc_now().isoformat(),
            "metadata": {},
        }

    @staticmethod
    def _sanitize_runtime_event_value(value: Any) -> Any:
        return RuntimeService._redact_sensitive_fields(RuntimeService._json_compatible(value))

    @staticmethod
    def _redact_sensitive_fields(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): (
                    REDACTED_VALUE
                    if RuntimeService._is_sensitive_event_field(str(key))
                    else RuntimeService._redact_sensitive_fields(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [RuntimeService._redact_sensitive_fields(item) for item in value]
        return value

    @staticmethod
    def _is_sensitive_event_field(field_name: str) -> bool:
        normalized = field_name.lower().replace("-", "_")
        return normalized in SENSITIVE_EVENT_FIELD_NAMES or any(
            marker in normalized for marker in ("api_key", "token", "secret", "password")
        )

    @staticmethod
    def _json_compatible(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(key): RuntimeService._json_compatible(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [RuntimeService._json_compatible(item) for item in value]
        if hasattr(value, "to_dict") and callable(value.to_dict):
            return RuntimeService._json_compatible(value.to_dict())
        if hasattr(value, "value"):
            return RuntimeService._json_compatible(value.value)
        return str(value)

    @staticmethod
    def _resolve_runtime_event_types(
        event_types: Iterable[str] | None = None,
        categories: Iterable[str] | None = None,
    ) -> list[SystemEvent]:
        requested = set(event_types or [])
        category_names = set(categories or [])
        if "all" in category_names or "*" in requested:
            return list(SystemEvent)

        category_map = RuntimeService._runtime_event_category_map()
        for category in category_names:
            if category not in category_map:
                raise ValueError(f"Unknown Runtime event category: {category}")
            requested.update(event_type.value for event_type in category_map[category])

        if not requested:
            requested.update(event_type.value for event_type in category_map["runtime_observable"])

        by_value = {event_type.value: event_type for event_type in SystemEvent}
        unknown = sorted(value for value in requested if value not in by_value)
        if unknown:
            raise ValueError(f"Unknown Runtime event types: {', '.join(unknown)}")
        return [by_value[value] for value in sorted(requested)]

    @staticmethod
    def _runtime_event_category_map() -> dict[str, tuple[SystemEvent, ...]]:
        categories = {
            "tool": (
                SystemEvent.TOOL_CALL_SELECTED,
                SystemEvent.TOOL_CALL_STARTED,
                SystemEvent.TOOL_CALL_PROGRESS,
                SystemEvent.TOOL_CALL_COMPLETED,
                SystemEvent.TOOL_CALL_FAILED,
            ),
            "model": (
                SystemEvent.MODEL_CALL_TIMING,
                SystemEvent.MODEL_AUTH,
                SystemEvent.MODEL_REQUEST_STARTED,
                SystemEvent.MODEL_RETRY_SCHEDULED,
                SystemEvent.MODEL_FIRST_TOKEN,
                SystemEvent.MODEL_COMPLETED,
                SystemEvent.MODEL_FAILED,
            ),
            "background": (
                SystemEvent.BACKGROUND_TASK_SUBMITTED,
                SystemEvent.BACKGROUND_TASK_COMPLETED,
                SystemEvent.BACKGROUND_TASK_FAILED,
                SystemEvent.BACKGROUND_WORKER_STARTED,
                SystemEvent.BACKGROUND_WORKER_IDLE,
                SystemEvent.BACKGROUND_WORKER_FAILED,
            ),
            "persistence": (
                SystemEvent.PERSISTENCE_SAVE_STARTED,
                SystemEvent.PERSISTENCE_SAVE_COMPLETED,
                SystemEvent.PERSISTENCE_SAVE_FAILED,
            ),
            "error": (
                SystemEvent.ERROR_OCCURRED,
                SystemEvent.MODEL_ERROR,
                SystemEvent.TOOL_ERROR,
            ),
        }
        categories["initiative_timer"] = (
            SystemEvent.INITIATIVE_TIMER_CREATED,
            SystemEvent.INITIATIVE_TIMER_UPDATED,
            SystemEvent.INITIATIVE_TIMER_CANCELLED,
            SystemEvent.INITIATIVE_TIMER_TRIGGERED,
            SystemEvent.INITIATIVE_TIMER_DISCARDED,
        )
        categories["runtime_observable"] = (
            *categories["tool"],
            *categories["model"],
            *categories["background"],
            *categories["persistence"],
            *categories["error"],
            *categories["initiative_timer"],
        )
        return categories

    @staticmethod
    def _normalize_session_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not isinstance(messages, list):
            raise ValueError("Messages must be a list")

        normalized: list[dict[str, Any]] = []
        allowed_roles = {"system", "user", "assistant", "tool"}
        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                raise ValueError(f"Message at index {index} must be an object")
            role = message.get("role")
            content = message.get("content")
            if role not in allowed_roles:
                raise ValueError(f"Message at index {index} has invalid role")
            if not isinstance(content, str):
                raise ValueError(f"Message at index {index} content must be a string")
            normalized.append(dict(message))
        return normalized

    @staticmethod
    def _find_regeneration_user_index(
        messages: list[dict[str, Any]], message_index: int
    ) -> int | None:
        for index in range(message_index, -1, -1):
            if messages[index].get("role") == "user":
                return index
        return None

    @staticmethod
    def _activate_session_for_regeneration(agent: Agent, session_id: str) -> None:
        if hasattr(agent, "resume_session"):
            if not agent.resume_session(session_id):
                raise ValueError(f"Session does not exist: {session_id}")
            return
        if not agent.session_manager.set_current_session(session_id):
            raise ValueError(f"Session does not exist: {session_id}")

    def _session_messages_payload(
        self,
        manager: Any,
        session: SessionContext,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        current = manager.get_current_session()
        is_current = bool(current and current.session_id == session.session_id)
        return {
            "session": self._session_payload(session),
            "session_id": session.session_id,
            "is_current": is_current,
            "messages": [dict(m) for m in messages],
            "message_count": len(messages),
        }

    @staticmethod
    def _session_payload(session: SessionContext | None) -> dict[str, Any]:
        if session is None:
            return {}
        return session.to_dict()
