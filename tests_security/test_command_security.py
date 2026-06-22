"""外部命令安全校验相关测试。"""

from __future__ import annotations

import pytest

from GensokyoAI.utils.command_security import (
    CommandSecurityError,
    validate_external_tool_command,
    validate_pip_packages,
)


def test_validate_external_tool_command_allows_safe_python() -> None:
    # 允许通过可执行文件启动普通 Python 模块
    validate_external_tool_command(["python", "-m", "mcp_server_example"])


def test_validate_external_tool_command_rejects_shell() -> None:
    with pytest.raises(CommandSecurityError):
        validate_external_tool_command(["bash", "-c", "rm -rf /"])


def test_validate_external_tool_command_rejects_python_c() -> None:
    with pytest.raises(CommandSecurityError):
        validate_external_tool_command(["python", "-c", "import os; os.system('x')"])


def test_validate_external_tool_command_rejects_metacharacters() -> None:
    with pytest.raises(CommandSecurityError):
        validate_external_tool_command(["python", "-m", "server; rm -rf /"])


def test_validate_external_tool_command_rejects_empty() -> None:
    with pytest.raises(CommandSecurityError):
        validate_external_tool_command([])


def test_validate_pip_packages_allows_whitelist() -> None:
    validate_pip_packages(["openai>=1.0.0", "anthropic>=0.20.0"])


def test_validate_pip_packages_rejects_metacharacters() -> None:
    with pytest.raises(CommandSecurityError):
        validate_pip_packages(["openai; rm -rf /"])


def test_validate_pip_packages_rejects_index_url() -> None:
    with pytest.raises(CommandSecurityError):
        validate_pip_packages(["--extra-index-url", "https://evil.com"])
