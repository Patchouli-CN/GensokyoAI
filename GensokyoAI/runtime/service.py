"""Frontend-agnostic runtime service for GensokyoAI.

This module is the public backend boundary for local clients, desktop apps,
web adapters, CLIs, and third-party frontends. It intentionally contains no
Flutter-specific behavior. Clients should interact with it through a stable RPC
transport such as ``bridge_main.py`` or a future HTTP/WebSocket adapter.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from GensokyoAI.core.agent import Agent
from GensokyoAI.core.config import ConfigLoader
from GensokyoAI.runtime.dependencies import dependency_status, install_dependencies
from GensokyoAI.runtime.rpc import dispatch_rpc, legacy_rpc_methods, rpc_methods
from GensokyoAI.session.context import SessionContext


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

    async def handle(self, method: str, params: dict[str, Any] | None = None) -> Any:
        return await dispatch_rpc(self, method, params)

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

    async def create_session(self) -> dict[str, Any]:
        agent = self._require_agent()
        async with self._lock:
            session = agent.create_session()
            return self._session_payload(session)

    async def list_sessions(self) -> list[dict[str, Any]]:
        agent = self._require_agent()
        return [self._session_payload(session) for session in agent.session_manager.list_sessions()]

    async def resume_session(self, session_id: str) -> dict[str, Any]:
        agent = self._require_agent()
        async with self._lock:
            if not agent.resume_session(session_id):
                raise ValueError(f"Session does not exist: {session_id}")
            session = agent.session_manager.get_current_session()
            return self._session_payload(session) if session else {}

    async def send_message(
        self,
        message: str,
        system_contexts: list[str] | None = None,
    ) -> dict[str, Any]:
        agent = self._require_agent()
        if not self.state.started:
            async with self._lock:
                if not self.state.started:
                    await agent.start()
                    self.state.started = True

        response = await agent.send(message, system_contexts)
        content = response.content if response else ""
        session = agent.session_manager.get_current_session()
        return {
            "role": "assistant",
            "content": content,
            "session": self._session_payload(session) if session else None,
        }

    async def dependency_status(self, providers: list[str] | None = None) -> dict[str, Any]:
        """Return optional Provider dependency status for generic clients."""

        return dependency_status(providers)

    async def install_dependencies(
        self,
        providers: list[str],
        scope: str = "current_runtime",
        timeout: int = 600,
    ) -> dict[str, Any]:
        """Install whitelisted optional Provider dependencies."""

        return install_dependencies(providers, scope=scope, timeout=timeout)

    async def shutdown(self) -> dict[str, Any]:
        async with self._lock:
            await self._shutdown_locked()
        return {"ok": True}

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
            "api_key",
            "stream",
            "think",
            "thinking_enabled",
            "reasoning_effort",
            "temperature",
            "top_p",
            "max_tokens",
            "timeout",
            "use_proxy",
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
    def _session_payload(session: SessionContext | None) -> dict[str, Any]:
        if session is None:
            return {}
        return session.to_dict()
