"""后端抽象基类"""

# GensokyoAI/backends/base.py

from abc import ABC, abstractmethod
from collections.abc import Callable


class BaseBackend(ABC):
    """后端基类"""

    @abstractmethod
    async def start(self) -> None:
        """启动后端"""
        pass

    @abstractmethod
    async def send(self, message: str, system_contexts: list[str] | None = None) -> str:
        """发送消息"""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """停止后端"""
        pass

    @abstractmethod
    def set_stream_handler(self, handler: Callable | None) -> None:
        """设置流式处理器"""
        pass
