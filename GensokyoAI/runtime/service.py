"""Frontend-agnostic runtime service for GensokyoAI.

This module is the public backend boundary for local clients, desktop apps,
web adapters, CLIs, and third-party frontends. It intentionally contains no
Flutter-specific behavior. Clients should interact with it through a stable RPC
transport such as ``bridge_main.py`` or a future HTTP/WebSocket adapter.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from GensokyoAI.core.agent import Agent
from GensokyoAI.core.agent.model_registry import ModelRegistryService
from GensokyoAI.core.agent.types import ModelInfo
from GensokyoAI.core.config import ConfigLoader
from GensokyoAI.runtime.dependencies import InstallScope, dependency_status, install_dependencies
from GensokyoAI.runtime.rpc import dispatch_rpc, legacy_rpc_methods, rpc_methods
from GensokyoAI.session.context import SessionContext
from GensokyoAI.tools.external_manager import ExternalToolManager


@dataclass(slots=True)
class RuntimeState:
    """Mutable state owned by a single runtime service instance."""

    root_dir: Path
    config_path: Path | None = None
    character_path: Path | None = None
    agent: Agent | None = None
    started: bool = False


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

        return {
            "name": "GensokyoAI Runtime",
            "protocol": "json-lines-rpc",
            "methods": rpc_methods(),
            "legacy_methods": legacy_rpc_methods(),
            "external_tools": self.external_tool_manager.source_status(include_tools=False),
        }

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
                    with open(path, "r", encoding="utf-8") as file:
                        data = yaml.safe_load(file) or {}
                    characters.append(
                        {
                            "id": path.stem,
                            "name": data.get("name", path.stem),
                            "path": str(path.relative_to(self.state.root_dir)),
                            "greeting": data.get("greeting", ""),
                            "metadata": data.get("metadata", {}),
                        }
                    )
                except Exception as exc:  # keep listing robust for broken user files
                    characters.append(
                        {
                            "id": path.stem,
                            "name": path.stem,
                            "path": str(path.relative_to(self.state.root_dir)),
                            "error": str(exc),
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
                self._session_payload(session)
                for session in agent.session_manager.list_sessions()
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
            "format": "gensokyoai.session.export",
            "version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(),
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
        agent = await self._ensure_started()
        response = await agent.send(message, system_contexts)
        content = response.content if response else ""
        session = agent.session_manager.get_current_session()
        return {
            "role": "assistant",
            "content": content,
            "session": self._session_payload(session) if session else None,
        }

    async def send_message_stream(
        self,
        message: str,
        system_contexts: list[str] | None = None,
    ) -> dict[str, Any]:
        agent = await self._ensure_started()
        events: list[dict[str, Any]] = []
        full_content = ""
        index = 0

        async for chunk in agent.send_stream(message, system_contexts):
            event = self._stream_chunk_payload(chunk, index)
            events.append(event)
            if event.get("type") == "content":
                full_content += event.get("content", "")
            index += 1

        session = agent.session_manager.get_current_session()
        finish_event = {
            "type": "finish",
            "index": index,
            "content": full_content,
            "session": self._session_payload(session) if session else None,
        }
        events.append(finish_event)
        return {
            "role": "assistant",
            "content": full_content,
            "events": events,
            "session": self._session_payload(session) if session else None,
        }

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

        return install_dependencies(providers, scope=scope, timeout=timeout)

    async def external_tool_status(self, include_tools: bool = True) -> dict[str, Any]:
        """Return external tool source status without exposing transport details."""

        return self.external_tool_manager.source_status(include_tools=include_tools)

    async def shutdown(self) -> dict[str, Any]:
        async with self._lock:
            await self._shutdown_locked()
        return {"ok": True}

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
            await agent.shutdown()
        self.state.agent = None
        self.state.started = False

    def _require_agent(self) -> Agent:
        if self.state.agent is None:
            raise RuntimeError("Runtime is not initialized. Call init first.")
        return self.state.agent

    def _resolve_optional(self, value: str | None) -> Path | None:
        if not value:
            return None
        path = Path(value)
        if not path.is_absolute():
            path = self.state.root_dir / path
        return path.resolve()

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
                return candidate.resolve()
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
        allowed = {
            "provider",
            "name",
            "base_url",
            "api_path",
            "api_key",
            "extra_headers",
            "model_capabilities_add",
            "model_capabilities_remove",
            "web_search_enabled",
            "web_search_strategy",
            "web_search_context_size",
            "web_search_user_location",
            "web_search_allow_fallback",
            "web_search_metadata",
            "stream",
            "think",
            "thinking_enabled",
            "reasoning_effort",
            "temperature",
            "top_p",
            "max_tokens",
            "timeout",
            "use_proxy",
            "retry_max_attempts",
            "retry_initial_delay",
            "retry_backoff_factor",
            "retry_status_codes",
        }
        RuntimeService._apply_overrides(model, overrides, allowed)

    @staticmethod
    def _apply_embedding_overrides(embedding: Any, overrides: dict[str, Any] | None) -> None:
        if not overrides:
            return
        allowed = {
            "provider",
            "name",
            "base_url",
            "api_key",
            "dimensions",
            "encoding_format",
            "timeout",
            "use_proxy",
        }
        RuntimeService._apply_overrides(embedding, overrides, allowed)

    @staticmethod
    def _apply_overrides(target: Any, overrides: dict[str, Any], allowed: set[str]) -> None:
        for key, value in overrides.items():
            if key not in allowed or value == "":
                continue
            setattr(target, key, value)

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
            event["timing"] = str(getattr(chunk, "timing"))
        references = getattr(chunk, "web_search_references", None)
        if references:
            event["web_search_references"] = [str(reference) for reference in references]
        diagnostics = getattr(chunk, "web_search_diagnostics", None)
        if diagnostics is not None:
            event["web_search_diagnostics"] = str(diagnostics)
        return event

    @staticmethod
    def _session_payload(session: SessionContext | None) -> dict[str, Any]:
        if session is None:
            return {}
        return session.to_dict()
