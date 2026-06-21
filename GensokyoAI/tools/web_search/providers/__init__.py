"""Web search Provider 包。"""

from .api import GenericAPISearchProvider
from .bing import BingSearchProvider
from .ddg import DuckDuckGoSearchProvider

__all__ = ["BingSearchProvider", "DuckDuckGoSearchProvider", "GenericAPISearchProvider"]
