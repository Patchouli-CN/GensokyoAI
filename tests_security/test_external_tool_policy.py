"""外部工具 / MCP 权限确认相关安全测试。"""

from __future__ import annotations

import pytest

from GensokyoAI.tools.errors import ToolExecutionError
from GensokyoAI.tools.external_manager import (
    ExternalToolDefinition,
    ExternalToolExecutionPolicy,
    ExternalToolManager,
    ExternalToolPermission,
    make_external_tool_name,
)


class _FakeSource:
    source_id = "test_server"
    command = None

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def list_tools(self) -> list[ExternalToolDefinition]:
        return [
            ExternalToolDefinition(
                source_id=self.source_id,
                tool_name="safe_tool",
                namespaced_name=make_external_tool_name(self.source_id, "safe_tool"),
                description="safe",
                schema={},
                metadata={"permissions": [ExternalToolPermission.SAFE.value]},
            ),
            ExternalToolDefinition(
                source_id=self.source_id,
                tool_name="dangerous_tool",
                namespaced_name=make_external_tool_name(self.source_id, "dangerous_tool"),
                description="dangerous",
                schema={},
                metadata={"permissions": [ExternalToolPermission.DESTRUCTIVE.value]},
            ),
        ]

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        return "done"


@pytest.mark.asyncio
async def test_risky_external_tool_requires_confirmation() -> None:
    manager = ExternalToolManager()
    manager.register_source(_FakeSource())
    await manager.start_source("test_server")

    with pytest.raises(ToolExecutionError) as exc_info:
        await manager.call_tool("external__test_server__dangerous_tool", {})

    assert "permission" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_safe_external_tool_allowed_by_default() -> None:
    manager = ExternalToolManager()
    manager.register_source(_FakeSource())
    await manager.start_source("test_server")

    result = await manager.call_tool("external__test_server__safe_tool", {})
    assert result == "done"


def test_policy_allows_safe_and_blocks_risky() -> None:
    policy = ExternalToolExecutionPolicy()
    assert policy.allows({ExternalToolPermission.SAFE.value}) is True
    assert policy.allows({ExternalToolPermission.DESTRUCTIVE.value}) is False
    assert policy.allows({ExternalToolPermission.FILESYSTEM.value}) is False


def test_policy_can_explicitly_allow_risky() -> None:
    policy = ExternalToolExecutionPolicy(
        allowed_permissions={
            ExternalToolPermission.SAFE.value,
            ExternalToolPermission.DESTRUCTIVE.value,
        },
        require_confirmation_for=set(),  # 显式关闭确认
    )
    assert policy.allows({ExternalToolPermission.DESTRUCTIVE.value}) is True
