"""Persistence migration helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .schema_versions import (
    GENSOKYOAI_CREATED_BY,
    MEMORY_SCHEMA_VERSION,
    MEMORY_STORE_FORMAT,
    SESSION_FILE_FORMAT,
    SESSION_SCHEMA_VERSION,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _migration_entry(*, from_version: int | None, to_version: int, reason: str) -> dict[str, Any]:
    return {
        "from_version": from_version,
        "to_version": to_version,
        "migrated_at": _now_iso(),
        "reason": reason,
    }


def migrate_session_file_payload(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Return a current-version session file payload and whether it changed."""

    migrated = dict(data)
    changed = False
    current_version = migrated.get("schema_version")

    if current_version == SESSION_SCHEMA_VERSION:
        migration_history = migrated.get("migration_history")
        if not isinstance(migration_history, list):
            migrated["migration_history"] = []
            changed = True
        if migrated.get("format") != SESSION_FILE_FORMAT:
            migrated["format"] = SESSION_FILE_FORMAT
            changed = True
        if migrated.get("created_by") != GENSOKYOAI_CREATED_BY:
            migrated["created_by"] = GENSOKYOAI_CREATED_BY
            changed = True
        return migrated, changed

    if "session" not in migrated:
        return migrated, False

    migrated.setdefault("format", SESSION_FILE_FORMAT)
    migrated["schema_version"] = SESSION_SCHEMA_VERSION
    migrated.setdefault("created_by", GENSOKYOAI_CREATED_BY)
    history = migrated.get("migration_history")
    if not isinstance(history, list):
        history = []
    history.append(
        _migration_entry(
            from_version=current_version if isinstance(current_version, int) else None,
            to_version=SESSION_SCHEMA_VERSION,
            reason="legacy_session_file_without_schema_version",
        )
    )
    migrated["migration_history"] = history
    migrated.setdefault("messages", [])
    return migrated, True


def make_session_file_payload(session: dict[str, Any], messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the current persisted session file payload."""

    return {
        "format": SESSION_FILE_FORMAT,
        "schema_version": SESSION_SCHEMA_VERSION,
        "created_by": GENSOKYOAI_CREATED_BY,
        "migration_history": [],
        "session": session,
        "messages": messages,
    }


def migrate_memory_store_payload(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Return a current-version topic memory store payload and whether it changed."""

    migrated = dict(data)
    changed = False
    current_version = migrated.get("schema_version")

    if current_version == MEMORY_SCHEMA_VERSION:
        migration_history = migrated.get("migration_history")
        if not isinstance(migration_history, list):
            migrated["migration_history"] = []
            changed = True
        if migrated.get("format") != MEMORY_STORE_FORMAT:
            migrated["format"] = MEMORY_STORE_FORMAT
            changed = True
        if migrated.get("created_by") != GENSOKYOAI_CREATED_BY:
            migrated["created_by"] = GENSOKYOAI_CREATED_BY
            changed = True
        return migrated, changed

    migrated.setdefault("format", MEMORY_STORE_FORMAT)
    migrated["schema_version"] = MEMORY_SCHEMA_VERSION
    migrated.setdefault("created_by", GENSOKYOAI_CREATED_BY)
    history = migrated.get("migration_history")
    if not isinstance(history, list):
        history = []
    history.append(
        _migration_entry(
            from_version=current_version if isinstance(current_version, int) else None,
            to_version=MEMORY_SCHEMA_VERSION,
            reason="legacy_topic_store_without_schema_version",
        )
    )
    migrated["migration_history"] = history
    migrated.setdefault("topics", [])
    migrated.setdefault("memories", [])
    return migrated, True


def make_memory_store_payload(topics: list[Any], memories: list[Any]) -> dict[str, Any]:
    """Build the current persisted topic memory store payload."""

    return {
        "format": MEMORY_STORE_FORMAT,
        "schema_version": MEMORY_SCHEMA_VERSION,
        "created_by": GENSOKYOAI_CREATED_BY,
        "migration_history": [],
        "topics": topics,
        "memories": memories,
    }
