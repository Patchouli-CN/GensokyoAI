"""Web/HTTP runtime server package for GensokyoAI."""

from .http_adapter import create_app

__all__ = ["create_app"]
