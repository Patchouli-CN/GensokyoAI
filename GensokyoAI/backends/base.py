"""后端抽象基类"""

# GensokyoAI/backends/base.py

from abc import ABC, abstractmethod
from collections.abc import Callable


class BaseBackend(ABC):
    """后端基类"""

    @abstractmethod
    async def start(self) -> None:
        """启动后端。"""
        raise NotImplementedError

    @abstractmethod
    async def send(self, message: str, system_contexts: list[str] | None = None) -> str:
        """发送消息并返回后端响应。"""
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        """停止后端。"""
        raise NotImplementedError

    @abstractmethod
    def set_stream_handler(self, handler: Callable | None) -> None:
        """设置流式处理器。"""
        raise NotImplementedError
