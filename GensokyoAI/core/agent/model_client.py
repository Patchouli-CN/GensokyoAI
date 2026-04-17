"""模型客户端 - 封装 Ollama 异步调用"""

# GensokyoAI/core/agent/model_client.py

import asyncio
from typing import AsyncIterator, Optional

from ollama import AsyncClient as OllamaAsyncClient
from ollama import ChatResponse, EmbeddingsResponse
from msgspec import Struct

from ..config import ModelConfig
from ..exceptions import ModelError
from ..events import Event, SystemEvent, EventBus
from ...utils.logging import logger


class StreamChunk(Struct):
    """流式响应块"""

    content: str = ""
    is_tool_call: bool = False
    tool_info: dict | None = None


class ModelClient:
    """模型客户端 - 纯粹封装 Ollama 调用"""

    def __init__(self, config: ModelConfig, event_bus: Optional["EventBus"] = None):
        self.config = config
        self._event_bus = event_bus
        self._client = self._build_client()
        logger.debug(f"ModelClient 初始化完成，模型: {config.name}")

    def _build_client(self) -> OllamaAsyncClient:
        """构建 Ollama 异步客户端"""
        return OllamaAsyncClient(host=self.config.base_url)

    def _build_options(self) -> dict:
        """构建模型选项"""
        return {
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "num_predict": self.config.max_tokens,
        }

    def _publish_error(self, error: Exception, context: dict) -> None:
        """发布错误事件 - 立即通知监听器"""
        if self._event_bus:
            error_str = str(error)
            status_code = "502" if "502" in error_str else None

            self._event_bus.publish(
                Event(
                    type=SystemEvent.MODEL_ERROR,
                    source="model_client",
                    data={
                        "model": self.config.name,
                        "error": error_str,
                        "error_type": type(error).__name__,
                        "status_code": status_code,
                        **context,
                    },
                )
            )

    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: Optional[list[dict]] = None,
    ) -> ChatResponse:
        """非流式调用模型"""
        kwargs = {
            "model": self.config.name,
            "messages": messages,
            "tools": tools,
            "options": self._build_options(),
        }

        if hasattr(self.config, "think"):
            kwargs["think"] = self.config.think

        try:
            logger.debug(f"非流式调用模型，消息数: {len(messages)}")
            response = await asyncio.wait_for(
                self._client.chat(**kwargs, stream=False),
                timeout=self.config.timeout,
            )
            logger.debug(f"模型响应完成，长度: {len(response.message.content or '')}")
            return response

        except asyncio.TimeoutError:
            error_msg = f"模型调用超时 ({self.config.timeout}s)"
            logger.error(error_msg)

            self._publish_error(
                ModelError(error_msg),
                {"context": "chat", "timeout": self.config.timeout, "message_count": len(messages)},
            )
            raise ModelError(error_msg)

        except Exception as e:
            error_msg = f"模型调用失败: {e}"
            logger.error(error_msg)

            error_str = str(e)
            if "502" in error_str:
                logger.warning("检测到 502 错误，可能是代理或连接问题")

            self._publish_error(
                e if isinstance(e, ModelError) else ModelError(error_msg),
                {"context": "chat", "message_count": len(messages)},
            )
            raise ModelError(error_msg) from e

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        tools: Optional[list[dict]] = None,
    ) -> AsyncIterator[StreamChunk]:
        """流式调用模型"""
        kwargs = {
            "model": self.config.name,
            "messages": messages,
            "tools": tools,
            "options": self._build_options(),
        }

        if hasattr(self.config, "think"):
            kwargs["think"] = self.config.think

        try:
            logger.debug(f"流式调用模型，消息数: {len(messages)}")
            stream = await self._client.chat(**kwargs, stream=True)

            async for chunk in stream:
                message = chunk.message

                if message.tool_calls:
                    yield StreamChunk(
                        is_tool_call=True,
                        tool_info={"message": message},
                    )
                elif message.content:
                    yield StreamChunk(content=message.content)

        except asyncio.TimeoutError:
            error_msg = f"流式调用超时 ({self.config.timeout}s)"
            logger.error(error_msg)
            self._publish_error(
                ModelError(error_msg), {"context": "chat_stream", "timeout": self.config.timeout}
            )
            raise ModelError(error_msg)

        except Exception as e:
            error_msg = f"流式模型调用失败: {e}"
            logger.error(error_msg)

            error_str = str(e)
            self._publish_error(
                e if isinstance(e, ModelError) else ModelError(error_msg),
                {
                    "context": "chat_stream",
                    "message_count": len(messages),
                },
            )
            raise ModelError(error_msg) from e

    def update_config(self, config: ModelConfig) -> None:
        """
        更新配置（例如运行时切换模型）

        Args:
            config: 新的模型配置
        """
        self.config = config
        self._client = self._build_client()
        logger.info(f"ModelClient 配置已更新，模型: {config.name}")

    async def embeddings(
        self,
        prompt: str,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        **kwargs,
    ) -> EmbeddingsResponse:
        """
        获取文本向量

        Args:
            prompt: 要向量化的文本
            model: 模型名称（可选，默认使用配置中的模型）
            timeout: 超时时间（可选，默认使用配置中的超时）
            **kwargs: 其他传递给 ollama embeddings 的参数

        Returns:
            EmbeddingsResponse: 包含 embedding 向量的响应

        Raises:
            ModelError: 调用失败或超时
        """
        try:
            logger.debug(f"调用 embeddings 模型，文本长度: {len(prompt)}")
            response = await asyncio.wait_for(
                self._client.embeddings(
                    model=model or self.config.name,
                    prompt=prompt,
                    **kwargs,
                ),
                timeout=timeout or self.config.timeout,
            )
            logger.debug(f"embeddings 响应完成，向量维度: {len(response.embedding)}")
            return response

        except asyncio.TimeoutError:
            logger.error(f"embeddings 调用超时 ({timeout or self.config.timeout}s)")
            raise ModelError(f"embeddings 调用超时 ({timeout or self.config.timeout}秒)")

        except Exception as e:
            logger.error(f"embeddings 调用失败: {e}")
            raise ModelError(f"embeddings 调用失败: {e}") from e

    async def embeddings_batch(
        self,
        prompts: list[str],
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        **kwargs,
    ) -> list[list[float]]:
        """
        批量获取文本向量（并行）

        Args:
            prompts: 要向量化的文本列表
            model: 模型名称（可选）
            timeout: 超时时间（可选）
            **kwargs: 其他参数

        Returns:
            向量列表
        """
        tasks = [self.embeddings(prompt, model, timeout, **kwargs) for prompt in prompts]
        responses = await asyncio.gather(*tasks)

        embeddings = []
        for resp in responses:
            if isinstance(resp, Exception):
                logger.warning(f"批量 embeddings 中有失败: {resp}")
                embeddings.append([])
            else:
                embeddings.append(resp.embedding)

        return embeddings

    @property
    def model_name(self) -> str:
        """获取当前使用的模型名称"""
        return self.config.name

    @property
    def client(self) -> OllamaAsyncClient:
        """模型客户端实例"""
        return self._client
