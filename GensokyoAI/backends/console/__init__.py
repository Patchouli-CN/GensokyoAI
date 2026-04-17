"""控制台后端具体实现模块"""
# GensokyoAI/backends/console/__init__.py

"""控制台后端模块"""

from ._impl import ConsoleBackend, ConsoleBackendBuilder

# 🔧 导入命令模块以触发装饰器注册
from . import commands

__all__ = [
    "ConsoleBackend",
    "ConsoleBackendBuilder",
]
