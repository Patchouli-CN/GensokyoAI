"""系统工具"""

# GenskoyoAI\tools\tool_builtin\system.py

import platform
from ..base import tool

@tool(description="获取系统信息")
def get_system_info() -> str:
    """获取操作系统和硬件信息"""
    return f"OS: {platform.system()} {platform.release()}, Python: {platform.python_version()}"
