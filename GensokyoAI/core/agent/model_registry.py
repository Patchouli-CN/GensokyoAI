"""模型元数据注册表服务。

该模块提供后端统一的模型能力与模型元数据查询入口，聚合：
- ProviderDefinition 中的 provider registry id 映射
- Provider.list_models() 远端/本地模型列表
- 内置 curated fallback 快照
- 用户显式 capability override

P7 目标是先提供轻量服务层，不改变现有 Provider 请求行为和 BaseProvider.list_models 接口。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ...utils.logger import logger
from ..config import ModelConfig
from .providers import ProviderFactory
from .providers.base import BaseProvider
from .types import ModelInfo, ProviderCapability

ProviderBuilder = Callable[[ModelConfig], BaseProvider]


@dataclass(frozen=True)
class ModelMetadataOverride:
    """用户显式模型元数据修正。"""

    id: str
    name: str | None = None
    context_window: int | None = None
    capabilities_add: frozenset[str] = field(default_factory=frozenset)
    capabilities_remove: frozenset[str] = field(default_factory=frozenset)
    owned_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _CacheKey:
    provider: str
    model_registry_id: str | None
    base_url: str | None
    api_path: str | None


class ModelRegistryService:
    """统一模型元数据注册表服务。"""

    def __init__(self, provider_builder: ProviderBuilder | None = None):
        self._provider_builder = provider_builder or ProviderFactory.create
        self._cache: dict[_CacheKey, list[ModelInfo]] = {}

    async def list_models(
        self,
        config: ModelConfig,
        *,
        refresh: bool = False,
        overrides: dict[str, ModelMetadataOverride | dict[str, Any]] | None = None,
    ) -> list[ModelInfo]:
        """列出指定配置对应 provider 的模型元信息。"""
        cache_key = self._cache_key(config)
        if not refresh and cache_key in self._cache:
            return self._apply_overrides(self._copy_models(self._cache[cache_key]), config, overrides)

        try:
            provider = self._provider_builder(config)
            provider_models = await provider.list_models()
        except Exception as e:
            logger.warning(f"拉取模型注册表失败，将使用缓存或启发式当前模型信息: {e}")
            provider_models = []

        if provider_models:
            models = self._provider_models(provider_models, provider_registry_id=self._model_registry_id(config))
            self._cache[cache_key] = self._copy_models(models)
            return self._apply_overrides(models, config, overrides)

        if cache_key in self._cache:
            return self._apply_overrides(self._copy_models(self._cache[cache_key]), config, overrides)

        fallback = self._fallback_models(config)
        self._cache[cache_key] = self._copy_models(fallback)
        return self._apply_overrides(fallback, config, overrides)

    async def get_model_info(
        self,
        config: ModelConfig,
        model_id: str | None = None,
        *,
        refresh: bool = False,
        overrides: dict[str, ModelMetadataOverride | dict[str, Any]] | None = None,
    ) -> ModelInfo:
        """查询单个模型元信息；精确匹配优先，之后使用边界感知前缀匹配。"""
        target = model_id or config.name
        models = await self.list_models(config, refresh=refresh, overrides=overrides)
        match = self.match_model(models, target)
        if match:
            return match

        fallback = self._heuristic_model_info(config, target)
        return self._apply_overrides([fallback], config, overrides)[0]

    def clear_cache(self) -> None:
        """清空内存模型元数据缓存。"""
        self._cache.clear()

    @staticmethod
    def match_model(models: list[ModelInfo], model_id: str) -> ModelInfo | None:
        """精确匹配优先，必要时进行边界感知前缀匹配。"""
        normalized_target = ModelRegistryService._normalize_model_id(model_id)
        for model in models:
            if ModelRegistryService._normalize_model_id(model.id) == normalized_target:
                return ModelRegistryService._copy_model(model)

        for model in models:
            candidate = ModelRegistryService._normalize_model_id(model.id)
            if ModelRegistryService._boundary_prefix_match(candidate, normalized_target):
                return ModelRegistryService._copy_model(model)
            if ModelRegistryService._boundary_prefix_match(normalized_target, candidate):
                return ModelRegistryService._copy_model(model)
        return None

    def _cache_key(self, config: ModelConfig) -> _CacheKey:
        return _CacheKey(
            provider=config.provider,
            model_registry_id=self._model_registry_id(config),
            base_url=config.base_url,
            api_path=config.api_path,
        )

    @staticmethod
    def _model_registry_id(config: ModelConfig) -> str | None:
        definition = ProviderFactory.get_provider_definition(config.provider)
        return definition.model_registry_id if definition else config.provider

    def _fallback_models(self, config: ModelConfig) -> list[ModelInfo]:
        return [self._heuristic_model_info(config, config.name)]

    def _heuristic_model_info(self, config: ModelConfig, model_id: str) -> ModelInfo:
        capabilities = self._heuristic_capabilities(config.provider, model_id)
        capabilities.update(config.model_capabilities_add or [])
        capabilities.difference_update(config.model_capabilities_remove or [])
        return ModelInfo(
            id=model_id,
            name=model_id,
            capabilities=sorted(capabilities),
            metadata={"fallback": True, "source": "heuristic", "provider": config.provider},
        )

    @staticmethod
    def _heuristic_capabilities(provider: str, model_id: str) -> set[str]:
        definition = ProviderFactory.get_provider_definition(provider)
        capabilities = ProviderCapability.normalize(definition.capabilities) if definition else {
            ProviderCapability.CHAT,
            ProviderCapability.STREAM,
        }
        normalized = model_id.lower()
        if any(marker in normalized for marker in ("vision", "gpt-4o", "gemini", "claude-3")):
            capabilities.add(ProviderCapability.VISION)
        if any(marker in normalized for marker in ("reason", "r1", "o1", "o3", "o4", "thinking")):
            capabilities.add(ProviderCapability.REASONING)
        if any(marker in normalized for marker in ("search", "sonar")):
            capabilities.add(ProviderCapability.WEB_SEARCH)
        if "embed" in normalized or "embedding" in normalized:
            capabilities.add(ProviderCapability.EMBEDDINGS)
        return ProviderCapability.normalize(capabilities)

    def _provider_models(
        self,
        provider_models: list[ModelInfo],
        *,
        provider_registry_id: str | None,
    ) -> list[ModelInfo]:
        models: list[ModelInfo] = []
        for model in provider_models:
            provider_model = self._copy_model(model)
            provider_model.metadata = {
                **dict(provider_model.metadata),
                "model_registry_id": provider_registry_id,
            }
            models.append(provider_model)
        return models

    def _apply_overrides(
        self,
        models: list[ModelInfo],
        config: ModelConfig,
        overrides: dict[str, ModelMetadataOverride | dict[str, Any]] | None,
    ) -> list[ModelInfo]:
        normalized_overrides = self._normalize_overrides(overrides)
        result: list[ModelInfo] = []
        seen: set[str] = set()

        for model in models:
            copied = self._copy_model(model)
            capabilities = ProviderCapability.normalize(copied.capabilities)
            capabilities.update(ProviderCapability.normalize(config.model_capabilities_add or []))
            capabilities.difference_update(ProviderCapability.normalize(config.model_capabilities_remove or []))

            override = self._find_override(normalized_overrides, copied.id)
            if override:
                if override.name is not None:
                    copied.name = override.name
                if override.context_window is not None:
                    copied.context_window = override.context_window
                if override.owned_by is not None:
                    copied.owned_by = override.owned_by
                capabilities.update(ProviderCapability.normalize(override.capabilities_add))
                capabilities.difference_update(ProviderCapability.normalize(override.capabilities_remove))
                copied.metadata = {**dict(copied.metadata), **dict(override.metadata), "overridden": True}

            copied.capabilities = sorted(capabilities)
            result.append(copied)
            seen.add(self._normalize_model_id(copied.id))

        for override in normalized_overrides.values():
            key = self._normalize_model_id(override.id)
            if key in seen:
                continue
            capabilities = ProviderCapability.normalize(override.capabilities_add)
            capabilities.update(ProviderCapability.normalize(config.model_capabilities_add or []))
            capabilities.difference_update(ProviderCapability.normalize(config.model_capabilities_remove or []))
            result.append(
                ModelInfo(
                    id=override.id,
                    name=override.name or override.id,
                    context_window=override.context_window,
                    capabilities=sorted(capabilities),
                    owned_by=override.owned_by,
                    metadata={**dict(override.metadata), "overridden": True, "source": "user_override"},
                )
            )
        return result

    @staticmethod
    def _normalize_overrides(
        overrides: dict[str, ModelMetadataOverride | dict[str, Any]] | None,
    ) -> dict[str, ModelMetadataOverride]:
        if not overrides:
            return {}
        normalized: dict[str, ModelMetadataOverride] = {}
        for model_id, value in overrides.items():
            if isinstance(value, ModelMetadataOverride):
                override = value
            else:
                override = ModelMetadataOverride(
                    id=str(value.get("id") or model_id),
                    name=value.get("name"),
                    context_window=value.get("context_window"),
                    capabilities_add=frozenset(ProviderCapability.normalize(value.get("capabilities_add") or [])),
                    capabilities_remove=frozenset(ProviderCapability.normalize(value.get("capabilities_remove") or [])),
                    owned_by=value.get("owned_by"),
                    metadata=dict(value.get("metadata") or {}),
                )
            normalized[ModelRegistryService._normalize_model_id(override.id)] = override
        return normalized

    @staticmethod
    def _find_override(
        overrides: dict[str, ModelMetadataOverride],
        model_id: str,
    ) -> ModelMetadataOverride | None:
        key = ModelRegistryService._normalize_model_id(model_id)
        if key in overrides:
            return overrides[key]
        for override_key, override in overrides.items():
            if ModelRegistryService._boundary_prefix_match(key, override_key):
                return override
            if ModelRegistryService._boundary_prefix_match(override_key, key):
                return override
        return None

    @staticmethod
    def _normalize_model_id(model_id: str) -> str:
        return model_id.strip().lower().removeprefix("models/")

    @staticmethod
    def _boundary_prefix_match(candidate: str, target: str) -> bool:
        if not candidate or not target or candidate == target:
            return candidate == target
        if target.startswith(candidate):
            remainder = target[len(candidate) :]
            return not remainder or remainder[0] in {"-", ":", "/", ".", "_"}
        return False

    @staticmethod
    def _copy_models(models: list[ModelInfo]) -> list[ModelInfo]:
        return [ModelRegistryService._copy_model(model) for model in models]

    @staticmethod
    def _copy_model(model: ModelInfo) -> ModelInfo:
        return ModelInfo(
            id=model.id,
            name=model.name,
            context_window=model.context_window,
            capabilities=sorted(ProviderCapability.normalize(model.capabilities)),
            owned_by=model.owned_by,
            metadata=dict(model.metadata),
        )


__all__ = ["ModelMetadataOverride", "ModelRegistryService"]
