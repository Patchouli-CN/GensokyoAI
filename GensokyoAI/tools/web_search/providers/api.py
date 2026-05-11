"""通用 JSON API Web Search Provider。"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

import aiohttp

from ....utils.request_utils import sanitize_response_body
from ..types import ProviderSearchResult, SearchItem
from .base import WebSearchProvider


class GenericAPISearchProvider(WebSearchProvider):
    """通过可配置 JSON API 执行搜索。"""

    name = "api"

    async def search(self, query: str, *, max_results: int | None = None) -> ProviderSearchResult:
        if not self.config.api.endpoint:
            return ProviderSearchResult(provider=self.name, status="disabled", error="未配置 tool.web_search.api.endpoint")
        try:
            payload = self._render_template(
                self.config.api.request_template,
                query=query,
                max_results=max_results or self.config.max_results,
            )
            params = self._render_template(
                self.config.api.query_params,
                query=query,
                max_results=max_results or self.config.max_results,
            )
            data = await self._request_json(payload, params)
            raw_items = self._get_path(data, self.config.api.results_path)
            if not isinstance(raw_items, list):
                return ProviderSearchResult(
                    provider=self.name,
                    status="failed",
                    error=f"API 响应中 {self.config.api.results_path} 不是数组",
                )
            items = [self._convert_item(item) for item in raw_items]
            items = [item for item in items if item.title and item.url]
            return ProviderSearchResult(provider=self.name, items=items[: max_results or self.config.max_results])
        except Exception as e:
            return ProviderSearchResult(provider=self.name, status="failed", error=str(e))

    async def _request_json(self, payload: dict[str, Any], params: dict[str, Any]) -> Any:
        api_config = self.config.api
        method = api_config.method.upper()
        endpoint = api_config.endpoint or ""
        if method == "GET" and params:
            endpoint = f"{endpoint}?{urlencode(params)}"

        headers = {"Content-Type": "application/json", "Accept": "application/json", **api_config.headers}
        if api_config.api_key:
            headers[api_config.api_key_header] = f"{api_config.api_key_prefix}{api_config.api_key}"

        body = None if method == "GET" else json.dumps(payload).encode("utf-8")
        timeout = aiohttp.ClientTimeout(total=self.config.timeout)
        try:
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.request(method, endpoint, data=body, headers=headers) as response,
            ):
                text = await response.text(encoding="utf-8", errors="replace")
                if response.status >= 400:
                    sanitized = sanitize_response_body(response.status, text)
                    raise RuntimeError(f"API 搜索 HTTP {response.status}: {sanitized}")
        except aiohttp.ClientError as e:
            raise RuntimeError(f"API 搜索网络错误: {e}") from e
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise RuntimeError("API 搜索返回了无效 JSON") from e

    def _convert_item(self, item: Any) -> SearchItem:
        title = self._get_path(item, self.config.api.title_path)
        url = self._get_path(item, self.config.api.url_path)
        snippet = self._get_path(item, self.config.api.snippet_path)
        published_at = (
            self._get_path(item, self.config.api.published_at_path)
            if self.config.api.published_at_path
            else None
        )
        return SearchItem(
            title=str(title or ""),
            url=str(url or ""),
            snippet=str(snippet or ""),
            source=self.name,
            published_at=str(published_at) if published_at else None,
            metadata=item if isinstance(item, dict) else {"raw": item},
        )

    @classmethod
    def _get_path(cls, data: Any, path: str | None) -> Any:
        if not path:
            return None
        current = data
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                current = current[int(part)]
            else:
                return None
        return current

    @classmethod
    def _render_template(cls, value: Any, **kwargs) -> Any:
        if isinstance(value, str):
            try:
                return value.format(**kwargs)
            except Exception:
                return value
        if isinstance(value, dict):
            return {key: cls._render_template(item, **kwargs) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._render_template(item, **kwargs) for item in value]
        return value
