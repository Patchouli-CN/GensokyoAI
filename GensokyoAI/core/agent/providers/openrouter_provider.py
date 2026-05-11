"""OpenRouter Provider 实现。

OpenRouter 使用 OpenAI-compatible Chat Completions 协议，但有独立的推荐 headers
和更丰富的 `/models` 元数据。这里复用 OpenAIProvider 的请求/响应转换能力，
只收敛 OpenRouter 专属默认值、headers、模型元信息与能力推断。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ....utils.logger import logger
from ....utils.request_utils import merge_headers
from ..types import ModelInfo, ProviderCapability
from .openai_provider import OpenAIProvider

if TYPE_CHECKING:
    from ...config import ModelConfig


class OpenRouterProvider(OpenAIProvider):
    """OpenRouter 一等 Provider。

    - 默认 base_url 为 https://openrouter.ai/api/v1
    - 请求仍使用 OpenAI Chat Completions `/chat/completions`
    - 默认注入 OpenRouter 推荐 headers，并允许 config.extra_headers 覆盖
    - 增强 OpenRouter `/models` 元数据解析和能力推断
    """

    DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
    DEFAULT_HEADERS = {
        "HTTP-Referer": "https://github.com/GensokyoAI/GensokyoAI",
        "X-Title": "GensokyoAI",
    }

    def __init__(self, config: ModelConfig):
        if not config.base_url:
            config.base_url = self.DEFAULT_BASE_URL
        super().__init__(config)
        logger.debug(
            f"OpenRouterProvider 初始化完成，base_url: {self._endpoint.api_host}, "
            f"api_path: {self._endpoint.api_path}, model: {config.name}"
        )

    @property
    def capabilities(self) -> set[str]:
        """OpenRouter Provider 级能力声明。"""
        return self.apply_model_capability_overrides(
            {
                ProviderCapability.CHAT,
                ProviderCapability.STREAM,
                ProviderCapability.TOOLS,
                ProviderCapability.CUSTOM_ENDPOINT,
            }
        )

    def merged_headers(self, *headers: dict | None) -> dict[str, str]:
        """合并 OpenRouter 默认 headers、用户 headers 与动态认证 headers。

        顺序上默认 headers 最先，config.extra_headers 后合并，因此用户配置可覆盖
        HTTP-Referer / X-Title。
        """
        return merge_headers(
            self.DEFAULT_HEADERS, self.config.extra_headers, self.auth_headers(), *headers
        )

    async def list_models(self) -> list[ModelInfo]:
        """拉取 OpenRouter `/models` 并转换为统一模型元信息。"""
        try:
            response = await self._client.models.list()
        except Exception as e:
            logger.warning(f"拉取 OpenRouter 模型列表失败，将返回当前配置模型作为 fallback: {e}")
            return [
                ModelInfo(
                    id=self.config.name,
                    name=self.config.name,
                    capabilities=sorted(self.apply_model_capability_overrides(self.capabilities)),
                    metadata={"fallback": True, "provider": "openrouter"},
                )
            ]

        models: list[ModelInfo] = []
        for item in getattr(response, "data", []) or []:
            model_id = getattr(item, "id", "") or ""
            if not model_id and isinstance(item, dict):
                model_id = item.get("id", "") or ""
            if not model_id:
                continue

            metadata = self._model_item_to_metadata(item)
            metadata["provider"] = "openrouter"
            context_window = self._extract_context_window(item, metadata)
            capabilities = self._infer_model_capabilities(item, metadata)
            models.append(
                ModelInfo(
                    id=model_id,
                    name=metadata.get("name") or model_id,
                    context_window=context_window,
                    capabilities=capabilities,
                    owned_by=getattr(item, "owned_by", None) or metadata.get("owned_by"),
                    metadata=metadata,
                )
            )
        return models

    @staticmethod
    def _model_item_to_metadata(item: Any) -> dict[str, Any]:
        """保留 OpenRouter 模型元数据。"""
        metadata = OpenAIProvider._model_item_to_metadata(item)
        for key in (
            "id",
            "name",
            "created",
            "description",
            "owned_by",
            "context_length",
            "architecture",
            "input_modalities",
            "output_modalities",
            "modalities",
            "supported_parameters",
            "supported_features",
            "pricing",
            "top_provider",
            "per_request_limits",
            "capabilities",
            "tools",
        ):
            if key in metadata:
                continue
            if isinstance(item, dict) and key in item:
                metadata[key] = item[key]
            elif hasattr(item, key):
                metadata[key] = getattr(item, key)
        return metadata

    def _infer_model_capabilities(self, item: Any, metadata: dict[str, Any]) -> list[str]:
        """根据 OpenRouter metadata 推断模型级能力。"""
        capabilities = set(self.capabilities)
        tokens = self._metadata_capability_tokens(metadata)

        modalities = metadata.get("input_modalities") or metadata.get("modalities") or []
        if isinstance(modalities, str):
            modalities = [modalities]
        normalized_modalities = {str(modality).lower() for modality in modalities}
        if {"image", "vision"} & normalized_modalities:
            capabilities.add(ProviderCapability.VISION)

        supported_parameters = metadata.get("supported_parameters") or []
        if isinstance(supported_parameters, str):
            supported_parameters = [supported_parameters]
        normalized_parameters = {str(param).lower() for param in supported_parameters}

        if {"tools", "tool_choice"} & normalized_parameters or {"tools", "tool_calling"} & tokens:
            capabilities.add(ProviderCapability.TOOLS)
        if {"response_format", "structured_outputs", "json_schema"} & normalized_parameters:
            capabilities.add(ProviderCapability.STRUCTURED_OUTPUT)

        pricing = metadata.get("pricing") or {}
        if isinstance(pricing, dict) and pricing.get("internal_reasoning") is not None:
            capabilities.add(ProviderCapability.REASONING)
        if {"reasoning", "include_reasoning", "reasoning_effort"} & normalized_parameters:
            capabilities.add(ProviderCapability.REASONING)

        model_id = (getattr(item, "id", "") or metadata.get("id", "") or "").lower()
        if any(marker in model_id for marker in ("reason", "r1", "o1", "o3", "o4")):
            capabilities.add(ProviderCapability.REASONING)
        if self._metadata_or_model_indicates_web_search(model_id, tokens):
            capabilities.add(ProviderCapability.WEB_SEARCH)

        return sorted(self.apply_model_capability_overrides(capabilities))
