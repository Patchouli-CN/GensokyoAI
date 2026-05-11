"""Web search 内置工具。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ...core.config import WebSearchToolConfig
from ..base import tool
from ..errors import ToolError, ToolExecutionError
from ..web_search.service import WebSearchService

if TYPE_CHECKING:
    from ...core.config import ToolConfig


_config = WebSearchToolConfig()
_service: WebSearchService | None = None


def configure_web_search_tool(config: ToolConfig) -> None:
    """注入工具配置。"""
    global _config, _service
    _config = config.web_search
    _service = WebSearchService(_config)


def get_web_search_service() -> WebSearchService:
    """获取 Web search 服务。"""
    global _service
    if _service is None:
        _service = WebSearchService(_config)
    return _service


@tool(
    name="web_search",
    description="联网搜索最新网页信息。适合查询新闻、当前事件、价格、版本、事实核验等需要外部实时信息的问题。",
)
async def web_search(
    query: str,
    max_results: int = 5,
    provider: str = "",
    time_range: str = "",
) -> str:
    """执行联网搜索并返回结构化 JSON。"""
    del time_range  # 第一轮仅保留参数兼容 API Provider 扩展。
    service = get_web_search_service()
    try:
        result = await service.search(
            query,
            max_results=max_results,
            provider=provider or None,
        )
    except Exception as e:
        raise ToolExecutionError(
            ToolError(
                error_code="web_search.unexpected_error",
                technical_message=f"web_search 执行异常: {e}",
                user_message="联网搜索执行失败。",
                recoverable=True,
                action_hint="请稍后重试；如果持续失败，请检查网络、代理或搜索 Provider 配置。",
                details={"query": query, "provider": provider or _config.provider, "exception_type": type(e).__name__},
            )
        ) from e

    if result.status in {"disabled", "failed"}:
        raise ToolExecutionError(_result_to_tool_error(result))
    return json.dumps(result.to_dict(), ensure_ascii=False)


def _result_to_tool_error(result) -> ToolError:
    """将 WebSearchResult 诊断映射为稳定工具错误码。"""
    if result.status == "disabled":
        return ToolError(
            error_code="web_search.disabled",
            technical_message=result.errors.get("config") or "web_search 工具未启用",
            user_message="联网搜索工具未启用。",
            recoverable=True,
            action_hint="请在配置中启用 tool.web_search.enabled。",
            details=result.to_dict()["diagnostics"],
        )
    if "provider" in result.errors:
        return ToolError(
            error_code="web_search.unsupported_provider",
            technical_message=result.errors["provider"],
            user_message="当前联网搜索 Provider 不可用。",
            recoverable=True,
            action_hint="请将 tool.web_search.provider 设置为 bing、api 或 mixed。",
            details=result.to_dict()["diagnostics"],
        )
    if result.errors:
        return ToolError(
            error_code="web_search.provider_failed",
            technical_message=result.fallback_reason or "web_search provider 执行失败",
            user_message="联网搜索 Provider 执行失败。",
            recoverable=True,
            action_hint="请检查网络、API key、endpoint 或稍后重试。",
            details=result.to_dict()["diagnostics"],
        )
    return ToolError(
        error_code="web_search.no_results",
        technical_message="web_search 未返回结果",
        user_message="联网搜索没有找到可用结果。",
        recoverable=True,
        action_hint="请换一个更具体的查询词后重试。",
        details=result.to_dict()["diagnostics"],
    )
