"""Ollama Provider 实现"""

# GensokyoAI/core/agent/providers/ollama_provider.py

import os
from typing import AsyncIterator, TYPE_CHECKING

from .base import BaseProvider
from ..types import (
    UnifiedResponse,
    UnifiedMessage,
    UnifiedEmbeddingResponse,
    StreamChunk,
    ToolCall,
    ToolCallFunction,
)
from ....utils.logger import logger

if TYPE_CHECKING:
    from ...config import ModelConfig


class OllamaProvider(BaseProvider):
    """
    Ollama Provider - 封装 Ollama 异步调用

    保持与原始 ModelClient 完全一致的行为
    """

    def __init__(self, config: "ModelConfig"):
        super().__init__(config)
        self._client = self._build_client()
        logger.debug(f"OllamaProvider 初始化完成，base_url: {config.base_url}")

    def _build_client(self):
        """构建 Ollama 异步客户端"""
        try:
            from ollama import AsyncClient as OllamaAsyncClient
        except ImportError:
            raise ImportError(
                "使用 Ollama Provider 需要安装 ollama 包: pip install ollama\n"
                "或者: pip install gensokyoai[ollama]"
            )

        # 根据配置决定是否使用代理
        if not self.config.use_proxy:
            os.environ.pop("HTTP_PROXY", None)
            os.environ.pop("HTTPS_PROXY", None)
            os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"
            logger.debug("已禁用代理，localhost 将直连")
        else:
            logger.debug(f"使用代理模式，base_url: {self.config.base_url}")

        return OllamaAsyncClient(host=self.config.base_url)

    async def chat(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        options: dict | None = None,
        **kwargs,
    ) -> UnifiedResponse:
        """非流式调用 Ollama"""
        call_kwargs = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "options": options or {},
            "stream": False,
        }

        # 处理 think 参数
        if kwargs.get("think"):
            model_lower = model.lower()
            if "deepseek" in model_lower or "r1" in model_lower:
                call_kwargs["think"] = True

        response = await self._client.chat(**call_kwargs)

        # 转换为统一类型
        return self._convert_response(response)

    async def chat_stream(  # type: ignore
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        options: dict | None = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """流式调用 Ollama"""
        call_kwargs = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "options": options or {},
            "stream": True,
        }

        # 处理 think 参数
        if kwargs.get("think"):
            model_lower = model.lower()
            if "deepseek" in model_lower or "r1" in model_lower:
                call_kwargs["think"] = True

        stream = await self._client.chat(**call_kwargs)

        async for chunk in stream:
            message = chunk.message

            if message.tool_calls:
                # 转换工具调用信息
                tool_calls = self._convert_tool_calls(message.tool_calls)
                unified_msg = UnifiedMessage(
                    role="assistant",
                    content=message.content or "",
                    tool_calls=tool_calls,
                )
                yield StreamChunk(
                    is_tool_call=True,
                    tool_info={"message": unified_msg},
                )
            elif message.content:
                yield StreamChunk(content=message.content)

    async def embeddings(
        self,
        model: str,
        prompt: str,
        **kwargs,
    ) -> UnifiedEmbeddingResponse:
        """获取文本向量"""
        response = await self._client.embeddings(
            model=model,
            prompt=prompt,
            **kwargs,
        )

        return UnifiedEmbeddingResponse(
            embedding=response.embedding,
            model=model,
        )

    def update_config(self, config: "ModelConfig") -> None:
        """更新配置并重建客户端"""
        super().update_config(config)
        self._client = self._build_client()
        logger.info(f"OllamaProvider 配置已更新，base_url: {config.base_url}")

    # ==================== 转换工具方法 ====================

    def _convert_response(self, response) -> UnifiedResponse:
        """将 ollama.ChatResponse 转换为 UnifiedResponse"""
        message = response.message
        tool_calls = None

        if message.tool_calls:
            tool_calls = self._convert_tool_calls(message.tool_calls)

        return UnifiedResponse(
            message=UnifiedMessage(
                role=message.role or "assistant",
                content=message.content or "",
                tool_calls=tool_calls,
            ),
            model=response.model if hasattr(response, "model") else "",
            done=True,
        )

    @staticmethod
    def _convert_tool_calls(ollama_tool_calls) -> list[ToolCall]:
        """将 ollama 的 tool_calls 转换为统一格式"""
        result = []
        for tc in ollama_tool_calls:
            result.append(
                ToolCall(
                    function=ToolCallFunction(
                        name=tc.function.name,
                        arguments=tc.function.arguments or {},
                        provider="ollama",
                    )
                )
            )
        return result
