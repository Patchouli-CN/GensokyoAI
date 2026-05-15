"""自有 Web search 内部类型。"""

from __future__ import annotations

from msgspec import Struct, field
from typing import Any


class SearchItem(Struct):
    """统一搜索结果项。"""

    title: str
    url: str
    snippet: str = ""
    source: str = ""
    published_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
            "published_at": self.published_at,
            "metadata": self.metadata,
        }


class ProviderSearchResult(Struct):
    """单个搜索 Provider 的执行结果。"""

    provider: str
    items: list[SearchItem] = field(default_factory=list)
    status: str = "completed"
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class WebSearchResult(Struct):
    """Web search 工具最终结果。"""

    query: str
    provider: str
    items: list[SearchItem] = field(default_factory=list)
    status: str = "completed"
    provider_status: dict[str, str] = field(default_factory=dict)
    fallback_reason: str | None = None
    cached: bool = False
    errors: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "provider": self.provider,
            "items": [item.to_dict() for item in self.items],
            "diagnostics": {
                "status": self.status,
                "provider_status": self.provider_status,
                "fallback_reason": self.fallback_reason,
                "cached": self.cached,
                "errors": self.errors,
                "result_count": len(self.items),
            },
        }
