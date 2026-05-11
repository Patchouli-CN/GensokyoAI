"""Web search Provider 基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..types import ProviderSearchResult

if TYPE_CHECKING:
    from ....core.config import WebSearchToolConfig


class WebSearchProvider(ABC):
    """自有 Web search Provider 抽象。"""

    name: str = "base"

    def __init__(self, config: WebSearchToolConfig):
        self.config = config

    @abstractmethod
    async def search(self, query: str, *, max_results: int | None = None) -> ProviderSearchResult:
        """执行搜索。"""
        ...
