"""Bing Web Search Provider。"""

from __future__ import annotations

import html
from html.parser import HTMLParser
from typing import TYPE_CHECKING
from urllib.parse import urlencode, urljoin, urlsplit

import aiohttp
from msgspec import Struct

from ....utils.request_utils import normalize_search_url
from ..types import ProviderSearchResult, SearchItem
from .base import WebSearchProvider

if TYPE_CHECKING:
    pass


class _LinkCandidate(Struct):
    """从 HTML 中抽取出的通用链接候选。"""

    title: str
    url: str
    text_index: int


class _GenericResultHTMLParser(HTMLParser):
    """通用搜索结果页链接抽取器。

    该解析器不绑定某个搜索页面的固定 CSS 结构，而是收集页面中的可见链接，
    后续再通过 URL 与文本质量规则筛选出可用搜索结果。
    """

    _SKIPPED_TAGS = {"script", "style", "noscript", "template", "svg"}

    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.candidates: list[_LinkCandidate] = []
        self.text_chunks: list[str] = []
        self._skip_depth = 0
        self._active_href: str | None = None
        self._active_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIPPED_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag != "a" or self._active_href is not None:
            return
        attrs_dict = {key.lower(): value or "" for key, value in attrs}
        href = attrs_dict.get("href", "").strip()
        if href:
            self._active_href = urljoin(self.base_url, href)
            self._active_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIPPED_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "a" and self._active_href is not None:
            title = _normalize_text(" ".join(self._active_text))
            if title:
                self.candidates.append(
                    _LinkCandidate(
                        title=title,
                        url=self._active_href,
                        text_index=max(len(self.text_chunks) - 1, 0),
                    )
                )
            self._active_href = None
            self._active_text = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = _normalize_text(data)
        if not text:
            return
        self.text_chunks.append(text)
        if self._active_href is not None:
            self._active_text.append(text)


def _normalize_text(value: str) -> str:
    """压缩空白并反转义 HTML 文本。"""
    return " ".join(html.unescape(value).split())


def _is_probably_content_url(url: str) -> bool:
    """过滤搜索页导航、站内链接和非网页链接。"""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = parts.netloc.lower()
    if scheme not in {"http", "https"} or not host:
        return False
    if host.endswith("bing.com") or host.endswith("microsoft.com"):
        return False
    if any(host.endswith(suffix) for suffix in (".bing.com", ".microsoft.com")):
        return False
    lowered_path = parts.path.lower()
    return not lowered_path.endswith(
        (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".css", ".js")
    )


def _make_snippet(
    candidate: _LinkCandidate, text_chunks: list[str], *, max_length: int = 220
) -> str:
    """用链接附近的可见文本合成摘要。"""
    start = max(candidate.text_index - 1, 0)
    end = min(candidate.text_index + 4, len(text_chunks))
    parts = []
    for text in text_chunks[start:end]:
        if text == candidate.title or text in candidate.title:
            continue
        if len(text) < 12:
            continue
        parts.append(text)
    snippet = _normalize_text(" ".join(parts))
    if len(snippet) > max_length:
        snippet = snippet[:max_length].rstrip() + "..."
    return snippet


class BingSearchProvider(WebSearchProvider):
    """Bing 网页搜索 Provider。"""

    name = "bing"

    async def search(self, query: str, *, max_results: int | None = None) -> ProviderSearchResult:
        limit = max_results or self.config.max_results
        try:
            body = await self._fetch("https://www.bing.com/search", {"q": query})
            parser = _GenericResultHTMLParser("https://www.bing.com/search")
            parser.feed(body)
            items = self._items_from_candidates(parser.candidates, parser.text_chunks, limit)
            return ProviderSearchResult(provider=self.name, items=items, status="completed")
        except Exception as e:
            return ProviderSearchResult(provider=self.name, status="failed", error=str(e))

    async def _fetch(self, url: str, params: dict[str, str]) -> str:
        full_url = f"{url}?{urlencode(params)}"
        headers = {
            "User-Agent": self.config.user_agent,
            "Accept-Language": self.config.region or "zh-CN,zh;q=0.9,en;q=0.7",
            "Referer": "https://www.bing.com/",
        }
        timeout = aiohttp.ClientTimeout(total=self.config.timeout)
        async with (
            aiohttp.ClientSession(timeout=timeout) as session,
            session.get(full_url, headers=headers) as response,
        ):
            return await response.text(encoding="utf-8", errors="replace")

    @staticmethod
    def _items_from_candidates(
        candidates: list[_LinkCandidate],
        text_chunks: list[str],
        limit: int,
    ) -> list[SearchItem]:
        items: list[SearchItem] = []
        seen: set[str] = set()
        for candidate in candidates:
            title = _normalize_text(candidate.title)
            if len(title) < 2 or len(title) > 180:
                continue
            canonical = normalize_search_url(candidate.url)
            if not _is_probably_content_url(canonical) or canonical in seen:
                continue
            seen.add(canonical)
            items.append(
                SearchItem(
                    title=title,
                    url=canonical,
                    snippet=_make_snippet(candidate, text_chunks),
                    source="bing",
                )
            )
            if len(items) >= limit:
                break
        return items
