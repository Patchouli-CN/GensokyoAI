"""后端模块

本模块提供了后端抽象基类和内置实现。

BaseBackend
    所有后端的抽象基类，定义了必须实现的接口。

ConsoleBackend
    内置的控制台后端实现，基于 Rich 库提供美化的终端交互。

    这个实现可作为开发自定义后端的参考示例：
    - 如何集成 CommandExecutor
    - 如何处理 CommandResult
    - 如何管理提示词上下文
    - 如何处理流式/非流式输出

ConsoleBackendBuilder
    用于链式配置 ConsoleBackend 的构建器。
"""

# GensokyoAI/backends/__init__.py

from .base import BaseBackend
from .console import ConsoleBackend, ConsoleBackendBuilder

__all__ = [
    "BaseBackend",
    "ConsoleBackend",
    "ConsoleBackendBuilder",
]
