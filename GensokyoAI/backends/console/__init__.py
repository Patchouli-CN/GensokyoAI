"""控制台后端具体实现模块"""
# GensokyoAI/backends/console/__init__.py

from . import commands as commands  # 导入命令模块以触发装饰器注册
from ._impl import ConsoleBackend, ConsoleBackendBuilder

__all__ = [
    "ConsoleBackend",
    "ConsoleBackendBuilder",
]
