"""LLM Provider 抽象基类"""

# GensokyoAI/core/agent/providers/base.py

from abc import ABC, abstractmethod
from typing import AsyncIterator, TYPE_CHECKING

if TYPE_CHECKING:
    from ..types import UnifiedResponse, UnifiedEmbeddingResponse, StreamChunk
    from ...config import ModelConfig


class BaseProvider(ABC):
    """
    LLM Provider 抽象基类

    所有 Provider 必须实现此接口，将各自 API 的响应转换为统一类型。

    紫：「边界是幻想乡的秩序，Provider 是 LLM 的边界。」
    """

    def __init__(self, config: "ModelConfig"):
        self.config = config

    @abstractmethod
    async def chat(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        options: dict | None = None,
        **kwargs,
    ) -> "UnifiedResponse":
        """
        非流式对话

        Args:
            model: 模型名称
            messages: 消息列表 [{"role": "user", "content": "..."}]
            tools: 工具定义列表（可选）
            options: 模型选项（temperature, top_p 等）
            **kwargs: 额外参数（如 think 等）

        Returns:
            UnifiedResponse: 统一响应
        """
        ...

    @abstractmethod
    async def chat_stream(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        options: dict | None = None,
        **kwargs,
    ) -> AsyncIterator["StreamChunk"]:
        """
        流式对话

        Args:
            model: 模型名称
            messages: 消息列表
            tools: 工具定义列表（可选）
            options: 模型选项
            **kwargs: 额外参数

        Yields:
            StreamChunk: 流式响应块
        """
        ...

    async def embeddings(
        self,
        model: str,
        prompt: str,
        **kwargs,
    ) -> "UnifiedEmbeddingResponse":
        """
        文本向量化

        Args:
            model: 模型名称
            prompt: 要向量化的文本
            **kwargs: 额外参数

        Returns:
            UnifiedEmbeddingResponse: 统一 embedding 响应

        Raises:
            NotImplementedError: 如果 Provider 不支持 embeddings
        """
        raise NotImplementedError(f"{self.__class__.__name__} 不支持 embeddings")

    def update_config(self, config: "ModelConfig") -> None:
        """更新配置"""
        self.config = config
