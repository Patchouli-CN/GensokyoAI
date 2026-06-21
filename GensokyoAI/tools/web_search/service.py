"""Web search 服务层：Provider 选择、合并、去重、缓存。"""

from __future__ import annotations

import asyncio
import time

from ...core.config import WebSearchToolConfig
from ...utils.request_utils import normalize_search_url
from .providers.api import GenericAPISearchProvider
from .providers.base import WebSearchProvider
from .providers.bing import BingSearchProvider
from .providers.ddg import DuckDuckGoSearchProvider
from .types import ProviderSearchResult, SearchItem, WebSearchResult


class WebSearchService:
    """自有 Web search 服务。"""

    def __init__(self, config: WebSearchToolConfig):
        self.config = config
        self._cache: dict[str, tuple[float, WebSearchResult]] = {}

    async def search(
        self,
        query: str,
        *,
        max_results: int | None = None,
        provider: str | None = None,
    ) -> WebSearchResult:
        """执行搜索。"""
        normalized_query = query.strip()
        if not normalized_query:
            return WebSearchResult(
                query=query,
                provider=provider or self.config.provider,
                status="failed",
                errors={"input": "query 不能为空"},
            )
        if not self.config.enabled:
            return WebSearchResult(
                query=normalized_query,
                provider=provider or self.config.provider,
                status="disabled",
                errors={"config": "tool.web_search.enabled 为 false"},
            )

        selected_provider = (provider or self.config.provider or "bing").lower()
        limit = max(1, min(max_results or self.config.max_results, self.config.max_results))
        cache_key = f"{selected_provider}:{normalized_query}:{limit}"
        cached = self._get_cached(cache_key)
        if cached:
            cached.cached = True
            return cached

        providers = self._build_providers(selected_provider)
        if not providers:
            return WebSearchResult(
                query=normalized_query,
                provider=selected_provider,
                status="failed",
                errors={"provider": f"不支持的 web_search provider: {selected_provider}"},
            )

        provider_results = await asyncio.gather(
            *(
                search_provider.search(normalized_query, max_results=limit)
                for search_provider in providers
            )
        )
        result = self._merge_results(normalized_query, selected_provider, provider_results, limit)
        self._set_cached(cache_key, result)
        return result

    def _build_providers(self, provider: str) -> list[WebSearchProvider]:
        providers: list[WebSearchProvider] = []
        if provider == "bing":
            providers.append(BingSearchProvider(self.config))
        if provider in ("ddg", "mixed"):
            providers.append(DuckDuckGoSearchProvider(self.config))
        if provider in ("api", "mixed"):
            providers.append(GenericAPISearchProvider(self.config))
        return providers

    def _merge_results(
        self,
        query: str,
        provider: str,
        results: list[ProviderSearchResult],
        max_results: int,
    ) -> WebSearchResult:
        provider_status = {result.provider: result.status for result in results}
        errors = {result.provider: result.error or "" for result in results if result.error}
        successful = [result for result in results if result.items]
        merged = self._rank_and_merge_results(successful, max_results)
        merged = self._deduplicate(merged)[:max_results]
        status = "completed" if merged and not errors else "partial" if merged else "failed"
        fallback_reason = (
            None
            if status == "completed"
            else "; ".join(f"{k}: {v}" for k, v in errors.items()) or None
        )
        return WebSearchResult(
            query=query,
            provider=provider,
            items=merged,
            status=status,
            provider_status=provider_status,
            fallback_reason=fallback_reason,
            errors=errors,
        )

    def _rank_and_merge_results(
        self,
        results: list[ProviderSearchResult],
        max_results: int,
    ) -> list[SearchItem]:
        """按来源优先级与结果质量排序合并多源结果。"""
        ranked: list[tuple[float, int, int, SearchItem]] = []
        for provider_index, result in enumerate(results):
            source_priority = self._source_priority(result.provider)
            for item_index, item in enumerate(result.items):
                score = self._item_score(item, source_priority, item_index)
                ranked.append((score, provider_index, item_index, item))
        ranked.sort(key=lambda value: (-value[0], value[1], value[2]))
        return [item for _, _, _, item in ranked[:max_results]]

    @staticmethod
    def _source_priority(provider: str) -> float:
        priorities = {
            "api": 1.0,
            "ddg": 0.95,
            "bing": 0.9,
        }
        return priorities.get(provider, 0.5)

    @staticmethod
    def _item_score(item: SearchItem, source_priority: float, item_index: int) -> float:
        title_score = min(len(item.title.strip()), 80) / 80 if item.title else 0.0
        snippet_length = len(item.snippet.strip()) if item.snippet else 0
        snippet_score = min(snippet_length, 180) / 180
        url_score = 1.0 if item.url.startswith(("http://", "https://")) else 0.0
        freshness_penalty = item_index * 0.01
        return (
            source_priority
            + title_score * 0.25
            + snippet_score * 0.2
            + url_score * 0.15
            - freshness_penalty
        )

    def _deduplicate(self, items: list[SearchItem]) -> list[SearchItem]:
        seen: set[str] = set()
        unique: list[SearchItem] = []
        for item in items:
            key = normalize_search_url(item.url)
            if not key or key in seen:
                continue
            seen.add(key)
            if (
                self.config.snippet_max_length
                and len(item.snippet) > self.config.snippet_max_length
            ):
                item.snippet = item.snippet[: self.config.snippet_max_length].rstrip() + "..."
            unique.append(item)
        return unique

    def _get_cached(self, key: str) -> WebSearchResult | None:
        if self.config.cache_ttl_seconds <= 0:
            return None
        value = self._cache.get(key)
        if not value:
            return None
        expires_at, result = value
        if time.time() >= expires_at:
            self._cache.pop(key, None)
            return None
        return WebSearchResult(
            query=result.query,
            provider=result.provider,
            items=list(result.items),
            status=result.status,
            provider_status=dict(result.provider_status),
            fallback_reason=result.fallback_reason,
            cached=True,
            errors=dict(result.errors),
        )

    def _set_cached(self, key: str, result: WebSearchResult) -> None:
        if self.config.cache_ttl_seconds <= 0:
            return
        self._cache[key] = (time.time() + self.config.cache_ttl_seconds, result)
