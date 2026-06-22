"""命令行安全校验工具。

用于检查外部子进程命令、依赖安装包名等是否包含 shell 元字符或高风险模式。
"""

from __future__ import annotations

import re
from typing import Any


class CommandSecurityError(ValueError):
    """命令安全校验失败时抛出。"""

    def __init__(self, message: str, *, detail: Any = None) -> None:
        super().__init__(message)
        self.detail = detail


# 高风险可执行文件/子命令模式
_HIGH_RISK_COMMAND_PATTERNS = {
    re.compile(r"\bbash\b", re.IGNORECASE),
    re.compile(r"\bsh\b", re.IGNORECASE),
    re.compile(r"\bcmd\b", re.IGNORECASE),
    re.compile(r"\bpowershell\b", re.IGNORECASE),
    re.compile(r"\bpwsh\b", re.IGNORECASE),
    re.compile(r"\beval\b", re.IGNORECASE),
    re.compile(r"\bexec\b", re.IGNORECASE),
}

# 明显的 shell 元字符；出现这些说明调用方可能把字符串拆错了或意图注入
_SHELL_METACHAR_PATTERN = re.compile(r"[;|`&$()\n\r]")

# pip 安装时可能被滥用来切换源的参数
_PIP_UNSAFE_ARG_PATTERN = re.compile(
    r"(^|\s)(--extra-index-url|--index-url|--find-links|-f|--trusted-host)(\s|$)",
    re.IGNORECASE,
)

# pip 包名中允许出现版本说明符，因此不能直接用上面的 shell 元字符集
_PIP_DISALLOWED_PATTERN = re.compile(r"[;|`&$()\n\r]")


def validate_external_tool_command(command: list[str]) -> None:
    """校验外部工具（MCP 等）启动命令是否安全。

    拒绝：
    - 空命令或非字符串元素
    - 可执行名为 bash / sh / cmd / powershell / eval / exec
    - 任何参数中包含 shell 元字符
    - 包含 python -c 这种可执行任意代码的模式

    Raises:
        CommandSecurityError: 校验失败。
    """

    if not isinstance(command, list) or not command:
        raise CommandSecurityError("外部工具命令必须是非空列表")

    for index, part in enumerate(command):
        if not isinstance(part, str):
            raise CommandSecurityError(
                f"外部工具命令第 {index} 个参数必须是字符串",
                detail={"command": command},
            )
        if not part:
            raise CommandSecurityError(
                "外部工具命令参数不能为空字符串",
                detail={"command": command},
            )

    executable = command[0]
    executable_lower = executable.lower()

    # 仅文件名（不含路径）判断高风险 shell
    executable_name = executable_lower.split("/")[-1].split("\\")[-1]
    if executable_name in {"bash", "sh", "cmd", "powershell", "pwsh", "eval", "exec"}:
        raise CommandSecurityError(
            f"禁止直接使用 {executable_name!r} 作为外部工具启动命令",
            detail={"command": command},
        )

    full_command = " ".join(command)
    if _SHELL_METACHAR_PATTERN.search(full_command):
        raise CommandSecurityError(
            "外部工具命令包含 shell 元字符",
            detail={"command": command},
        )

    # 禁止 python -c / python -m 中跟代码字符串的模糊风险
    if executable_name.startswith("python") and len(command) >= 3 and command[1] == "-c":
        raise CommandSecurityError(
            "禁止通过 python -c 启动外部工具",
            detail={"command": command},
        )


def validate_pip_packages(packages: list[str]) -> None:
    """校验 pip 安装包名列表是否安全。

    当前 package 名称来自硬编码白名单，但仍需防止未来配置/自定义把
    任意字符串传入。拒绝包含 shell 元字符或可用于切换源的参数。

    Raises:
        CommandSecurityError: 校验失败。
    """

    if not isinstance(packages, list):
        raise CommandSecurityError("packages 必须是列表")

    for package in packages:
        if not isinstance(package, str) or not package:
            raise CommandSecurityError(
                "包名必须是非空字符串",
                detail={"package": package},
            )
        if _PIP_DISALLOWED_PATTERN.search(package):
            raise CommandSecurityError(
                f"包名包含非法字符: {package!r}",
                detail={"package": package},
            )
        if _PIP_UNSAFE_ARG_PATTERN.search(" " + package):
            raise CommandSecurityError(
                f"包名疑似包含 pip 源切换参数: {package!r}",
                detail={"package": package},
            )


__all__ = [
    "CommandSecurityError",
    "validate_external_tool_command",
    "validate_pip_packages",
]
