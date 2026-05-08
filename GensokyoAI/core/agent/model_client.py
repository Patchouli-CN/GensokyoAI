"""模型客户端 - Facade 模式，委托给可插拔的 Provider"""

# GensokyoAI/core/agent/model_client.py

import asyncio
from typing import AsyncIterator, Optional

from .types import UnifiedResponse, UnifiedMessage, UnifiedEmbeddingResponse, StreamChunk, ProviderCapability
from .providers import ProviderFactory, BaseProvider
from .providers.request_utils import ModelAPIError, is_retryable_error, normalize_model_error
from ..config import EmbeddingConfig, ModelConfig
from ..exceptions import ModelError
from ..events import Event, SystemEvent, EventBus
from ...utils.logger import logger


class ModelClient:
    """
    模型客户端 - Facade 层

    对外暴露统一接口，内部委托给具体的 Provider 实现。
    消费方（ThinkEngine、EpisodicMemory 等）只需要和 ModelClient 交互，
    不需要关心底层使用的是 Ollama、OpenAI 还是其他 API。
    """

    def __init__(
        self,
        config: ModelConfig,
        event_bus: Optional["EventBus"] = None,
        embedding_config: EmbeddingConfig | None = None,
    ):
        self.config = config
        self._event_bus = event_bus
        self._provider: BaseProvider = ProviderFactory.create(config)
        self._embedding_provider: BaseProvider | None = None
        self._embedding_config = embedding_config or EmbeddingConfig()
        logger.debug(f"ModelClient 初始化完成，Provider: {config.provider}, 模型: {config.name}")

    def _build_options(self) -> dict:
        """构建模型选项"""
        return {
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "num_predict": self.config.max_tokens,
        }

    def _build_embedding_config(self) -> ModelConfig:
        """构建独立的 Embedding Provider 配置。"""
        embedding_config = self._embedding_config
        if not embedding_config.name:
            raise ModelError(
                "未配置 embedding.name，不能使用聊天模型作为 embedding 模型；"
                "请在配置文件的 embedding.name 中指定 embedding 模型"
            )

        return ModelConfig(
            provider=embedding_config.provider or self.config.provider,
            name=embedding_config.name,
            base_url=embedding_config.base_url or self.config.base_url,
            api_key=embedding_config.api_key or self.config.api_key,
            extra_headers=self.config.extra_headers,
            timeout=embedding_config.timeout or self.config.timeout,
            thinking_enabled=False,
            retry_max_attempts=self.config.retry_max_attempts,
            retry_initial_delay=self.config.retry_initial_delay,
            retry_backoff_factor=self.config.retry_backoff_factor,
            use_proxy=(
                embedding_config.use_proxy
                if embedding_config.use_proxy is not None
                else self.config.use_proxy
            ),
        )

    def _get_embedding_provider(self) -> tuple[BaseProvider, ModelConfig]:
        """获取或创建独立 Embedding Provider。"""
        embedding_model_config = self._build_embedding_config()
        if self._embedding_provider is None:
            self._embedding_provider = ProviderFactory.create(embedding_model_config)
            logger.info(
                f"创建 Embedding Provider: {embedding_model_config.provider}, "
                f"模型: {embedding_model_config.name}"
            )
        return self._embedding_provider, embedding_model_config

    def _build_embedding_kwargs(self, kwargs: dict) -> dict:
        """合并配置文件和调用方传入的 embedding 参数。"""
        merged = dict(kwargs)
        if self._embedding_config.dimensions is not None:
            merged.setdefault("dimensions", self._embedding_config.dimensions)
        if self._embedding_config.encoding_format:
            merged.setdefault("encoding_format", self._embedding_config.encoding_format)
        return merged

    def _publish_error(self, error: Exception, context: dict) -> None:
        """发布错误事件 - 立即通知监听器"""
        if self._event_bus:
            error_str = str(error)
            data = {
                "model": self.config.name,
                "provider": self.config.provider,
                "error": error_str,
                "error_type": type(error).__name__,
                **context,
            }
            if isinstance(error, ModelAPIError):
                data.update(
                    {
                        "status_code": error.status_code,
                        "response_body": error.response_body,
                        "endpoint": error.endpoint,
                        "retryable": error.retryable,
                    }
                )

            self._event_bus.publish(
                Event(
                    type=SystemEvent.MODEL_ERROR,
                    source="model_client",
                    data=data,
                )
            )

    async def _call_with_retry(self, call_factory, *, context: str, model: str):
        """按配置对可重试 API 错误进行指数退避重试。"""
        max_attempts = max(1, self.config.retry_max_attempts)
        delay = max(0.0, self.config.retry_initial_delay)
        backoff = max(1.0, self.config.retry_backoff_factor)

        for attempt in range(1, max_attempts + 1):
            try:
                return await asyncio.wait_for(call_factory(), timeout=self.config.timeout)
            except asyncio.TimeoutError:
                raise
            except asyncio.CancelledError:
                raise
            except Exception as e:
                normalized = normalize_model_error(
                    e,
                    provider=self.config.provider,
                    model=model,
                    endpoint=getattr(self._provider, "endpoint", None),
                )
                if attempt >= max_attempts or not is_retryable_error(normalized):
                    raise normalized from e

                logger.warning(
                    f"模型 API 调用失败，准备重试 ({attempt + 1}/{max_attempts})，"
                    f"context={context}, status={normalized.status_code}, error={normalized}"
                )
                if self._event_bus:
                    self._event_bus.publish(
                        Event(
                            type=SystemEvent.MODEL_ERROR,
                            source="model_client",
                            data={
                                "model": model,
                                "provider": self.config.provider,
                                "context": context,
                                "status": "retrying",
                                "attempt": attempt + 1,
                                "max_attempts": max_attempts,
                                "error": str(normalized),
                                "status_code": normalized.status_code,
                                "endpoint": normalized.endpoint,
                            },
                        )
                    )
                if delay:
                    await asyncio.sleep(delay)
                    delay *= backoff

    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: Optional[list[dict]] = None,
        model: Optional[str] = None,
        options: Optional[dict] = None,
        **kwargs,
    ) -> UnifiedResponse:
        """
        非流式调用模型

        Args:
            messages: 消息列表
            tools: 工具定义列表（可选）
            model: 模型名称（可选，默认使用配置中的模型）
            options: 模型选项（可选，默认使用配置构建）
            **kwargs: 额外参数（如 think 等）

        Returns:
            UnifiedResponse: 统一响应

        Raises:
            ModelError: 调用失败或超时
        """
        call_model = model or self.config.name
        call_options = options or self._build_options()

        # 传递 think 参数
        if hasattr(self.config, "think") and self.config.think:
            kwargs.setdefault("think", True)

        try:
            logger.debug(f"非流式调用模型，消息数: {len(messages)}")
            response = await self._call_with_retry(
                lambda: self._provider.chat(
                    model=call_model,
                    messages=messages,
                    tools=tools,
                    options=call_options,
                    **kwargs,
                ),
                context="chat",
                model=call_model,
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
            normalized = (
                e
                if isinstance(e, ModelAPIError)
                else normalize_model_error(e, provider=self.config.provider, model=call_model)
            )
            error_msg = f"模型调用失败: {normalized}"
            logger.opt(colors=False).error(error_msg)

            self._publish_error(
                normalized,
                {"context": "chat", "message_count": len(messages)},
            )
            raise ModelError(error_msg) from e

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        tools: Optional[list[dict]] = None,
        model: Optional[str] = None,
        options: Optional[dict] = None,
        extra_body: Optional[dict] = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """
        流式调用模型

        Args:
            messages: 消息列表
            tools: 工具定义列表（可选）
            model: 模型名称（可选，默认使用配置中的模型）
            options: 模型选项（可选，默认使用配置构建）
            **kwargs: 额外参数

        Yields:
            StreamChunk: 流式响应块

        Raises:
            ModelError: 调用失败或超时
        """
        call_model = model or self.config.name
        call_options = options or self._build_options()

        # 传递 think 参数
        if hasattr(self.config, "think") and self.config.think:
            kwargs.setdefault("think", True)

        try:
            logger.debug(f"流式调用模型，消息数: {len(messages)}")
            max_attempts = max(1, self.config.retry_max_attempts)
            delay = max(0.0, self.config.retry_initial_delay)
            backoff = max(1.0, self.config.retry_backoff_factor)

            for attempt in range(1, max_attempts + 1):
                try:
                    async for chunk in self._provider.chat_stream(
                        model=call_model,
                        messages=messages,
                        tools=tools,
                        options=call_options,
                        extra_body=extra_body,
                        **kwargs,
                    ):  # type: ignore
                        yield chunk
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    normalized = normalize_model_error(
                        e,
                        provider=self.config.provider,
                        model=call_model,
                        endpoint=getattr(self._provider, "endpoint", None),
                    )
                    if attempt >= max_attempts or not is_retryable_error(normalized):
                        raise normalized from e
                    logger.warning(
                        f"流式模型 API 调用失败，准备重试 ({attempt + 1}/{max_attempts})，"
                        f"status={normalized.status_code}, error={normalized}"
                    )
                    yield StreamChunk(
                        type="status",
                        status="retrying",
                        error=str(normalized),
                        finish_reason=None,
                    )
                    if delay:
                        await asyncio.sleep(delay)
                        delay *= backoff

        except asyncio.TimeoutError:
            error_msg = f"流式调用超时 ({self.config.timeout}s)"
            logger.error(error_msg)
            self._publish_error(
                ModelError(error_msg), {"context": "chat_stream", "timeout": self.config.timeout}
            )
            raise ModelError(error_msg)

        except Exception as e:
            normalized = (
                e
                if isinstance(e, ModelAPIError)
                else normalize_model_error(e, provider=self.config.provider, model=call_model)
            )
            error_msg = f"流式模型调用失败: {normalized}"
            logger.opt(colors=False).error(error_msg)

            self._publish_error(
                normalized,
                {
                    "context": "chat_stream",
                    "message_count": len(messages),
                },
            )
            raise ModelError(error_msg) from e

    def update_embedding_config(self, embedding_config: EmbeddingConfig | None) -> None:
        """更新独立 Embedding 配置并重建 Embedding Provider。"""
        self._embedding_config = embedding_config or EmbeddingConfig()
        self._embedding_provider = None
        logger.info("ModelClient Embedding 配置已更新")

    def update_config(self, config: ModelConfig) -> None:
        """
        更新配置（例如运行时切换模型或 Provider）

        Args:
            config: 新的模型配置
        """
        old_provider = self.config.provider
        self.config = config

        if config.provider != old_provider:
            # Provider 类型变了，需要重建
            self._provider = ProviderFactory.create(config)
            logger.info(
                f"ModelClient Provider 已切换: {old_provider} -> {config.provider}, "
                f"模型: {config.name}"
            )
        else:
            # 同一 Provider，只更新配置
            self._provider.update_config(config)
            logger.info(f"ModelClient 配置已更新，Provider: {config.provider}, 模型: {config.name}")

    async def embeddings(
        self,
        prompt: str,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        **kwargs,
    ) -> UnifiedEmbeddingResponse:
        """
        获取文本向量

        Args:
            prompt: 要向量化的文本
            model: 模型名称（可选，默认使用 embedding.name）
            timeout: 超时时间（可选，默认使用配置中的超时）
            **kwargs: 其他传递给 Provider 的参数

        Returns:
            UnifiedEmbeddingResponse: 统一 embedding 响应

        Raises:
            ModelError: 调用失败或超时
        """
        try:
            embedding_provider, embedding_model_config = self._get_embedding_provider()
            call_model = model or embedding_model_config.name
            call_timeout = timeout or embedding_model_config.timeout
            embedding_kwargs = self._build_embedding_kwargs(kwargs)
            logger.debug(
                f"调用 embeddings 模型，Provider: {embedding_model_config.provider}, "
                f"模型: {call_model}, 文本长度: {len(prompt)}"
            )
            response = await asyncio.wait_for(
                embedding_provider.embeddings(
                    model=call_model,
                    prompt=prompt,
                    **embedding_kwargs,
                ),
                timeout=call_timeout,
            )
            logger.debug(f"embeddings 响应完成，向量维度: {len(response.embedding)}")
            return response

        except asyncio.TimeoutError:
            effective_timeout = timeout or self._embedding_config.timeout or self.config.timeout
            logger.error(f"embeddings 调用超时 ({effective_timeout}s)")
            raise ModelError(f"embeddings 调用超时 ({effective_timeout}秒)")

        except NotImplementedError as e:
            embedding_provider_name = self._embedding_config.provider or self.config.provider
            logger.warning(f"当前 Provider 不支持 embeddings: {e}")
            raise ModelError(
                f"当前 embedding Provider ({embedding_provider_name}) 不支持 embeddings"
            ) from e

        except Exception as e:
            normalized = normalize_model_error(e, provider=self.config.provider, model=model)
            logger.error(f"embeddings 调用失败: {normalized}")
            raise ModelError(f"embeddings 调用失败: {normalized}") from e

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
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        embeddings = []
        for resp in responses:
            if isinstance(resp, BaseException):
                logger.warning(f"批量 embeddings 中有异常: {resp}")
                embeddings.append([])
            else:
                embeddings.append(resp.embedding)

        return embeddings

    @property
    def model_name(self) -> str:
        """获取当前使用的模型名称"""
        return self.config.name

    @property
    def provider_name(self) -> str:
        """获取当前使用的 Provider 名称"""
        return self.config.provider

    @property
    def provider(self) -> BaseProvider:
        """获取 Provider 实例（仅供高级用途）"""
        return self._provider

    @property
    def supports_embeddings(self) -> bool:
        """检查当前 Provider 是否支持 embeddings"""
        if not self._embedding_config.name:
            return False

        try:
            embedding_provider, _ = self._get_embedding_provider()
        except Exception:
            return False

        if embedding_provider.supports(ProviderCapability.EMBEDDINGS):
            return True

        # 兼容旧自定义 Provider：检查是否覆盖了 BaseProvider 的默认实现。
        from .providers.base import BaseProvider as _Base

        return type(embedding_provider).embeddings is not _Base.embeddings
