"""DuckDuckGo Web Search Provider using the ``ddgs`` package."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ddgs import DDGS
from ddgs.exceptions import DDGSException

from ....utils.request_utils import normalize_search_url
from ..types import ProviderSearchResult, SearchItem
from .base import WebSearchProvider

if TYPE_CHECKING:
    from ....core.config import WebSearchToolConfig


class DuckDuckGoSearchProvider(WebSearchProvider):
    """DuckDuckGo 网页搜索 Provider。

    ``ddgs`` 当前只提供同步 API，因此在异步上下文中通过
    :func:`asyncio.to_thread` 调用，避免阻塞事件循环。
    """

    name = "ddg"

    def __init__(self, config: WebSearchToolConfig):
        super().__init__(config)
        self._ddgs = DDGS(timeout=config.timeout)

    async def search(self, query: str, *, max_results: int | None = None) -> ProviderSearchResult:
        limit = max_results or self.config.max_results
        try:
            results = await asyncio.to_thread(
                self._ddgs.text,
                query,
                max_results=limit,
                region=self.config.region or "wt-wt",
                safesearch=self._map_safe_search(self.config.safe_search),
                timelimit=None,
            )
            items = [
                SearchItem(
                    title=str(result.get("title", "")),
                    url=normalize_search_url(str(result.get("href", ""))),
                    snippet=str(result.get("body", "")),
                    source=self.name,
                )
                for result in results
                if result.get("href")
            ]
            return ProviderSearchResult(provider=self.name, items=items, status="completed")
        except DDGSException as error:
            return ProviderSearchResult(provider=self.name, status="failed", error=str(error))
        except Exception as error:  # noqa: BLE001
            return ProviderSearchResult(provider=self.name, status="failed", error=str(error))

    @staticmethod
    def _map_safe_search(value: str) -> str:
        mapping = {
            "off": "off",
            "moderate": "moderate",
            "strict": "on",
        }
        return mapping.get(value.lower(), "moderate")
