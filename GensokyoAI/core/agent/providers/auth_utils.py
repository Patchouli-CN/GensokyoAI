"""Provider 认证辅助工具。"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import aiohttp

from ....utils.request_utils import merge_headers

if TYPE_CHECKING:
    from ...config import AuthConfig

SENSITIVE_KEYS = {
    "access_token",
    "refresh_token",
    "client_secret",
    "authorization",
    "api_key",
    "token",
}


class AuthRefreshError(RuntimeError):
    """刷新认证 token 失败。"""


class TokenRefreshManager:
    """OAuth/token refresh 管理器，提供并发保护。"""

    def __init__(self, auth_config: AuthConfig):
        self.auth_config = auth_config
        self._lock = asyncio.Lock()

    def is_enabled(self) -> bool:
        return bool(self.auth_config and self.auth_config.auth_type)

    def needs_refresh(self, *, force: bool = False) -> bool:
        """判断是否需要刷新 token。"""
        if not self.is_enabled():
            return False
        if force:
            return True
        if not self.auth_config.access_token:
            return True
        if self.auth_config.expires_at is None:
            return False
        return time.time() >= (
            self.auth_config.expires_at - self.auth_config.refresh_before_seconds
        )

    async def ensure_token(self, *, force: bool = False) -> str | None:
        """确保可用 access token，并在必要时刷新。"""
        if not self.is_enabled():
            return None
        if not self.needs_refresh(force=force):
            return self.auth_config.access_token
        async with self._lock:
            if not self.needs_refresh(force=force):
                return self.auth_config.access_token
            return await self._refresh()

    def auth_headers(self) -> dict[str, str]:
        """根据当前 token 生成认证请求头。"""
        if not self.is_enabled() or not self.auth_config.access_token:
            return {}
        if self.auth_config.auth_type in {"bearer", "oauth", "oauth2"}:
            return {"Authorization": f"Bearer {self.auth_config.access_token}"}
        return {}

    async def _refresh(self) -> str:
        if not self.auth_config.token_url:
            raise AuthRefreshError("未配置 auth.token_url，无法刷新 token")

        body: dict[str, Any] = dict(self.auth_config.auth_body or {})
        body.setdefault("grant_type", "refresh_token")
        if self.auth_config.refresh_token:
            body.setdefault("refresh_token", self.auth_config.refresh_token)
        if self.auth_config.client_id:
            body.setdefault("client_id", self.auth_config.client_id)
        if self.auth_config.client_secret:
            body.setdefault("client_secret", self.auth_config.client_secret)
        if self.auth_config.scope:
            body.setdefault("scope", self.auth_config.scope)

        headers = merge_headers(
            {"Content-Type": "application/x-www-form-urlencoded"},
            self.auth_config.auth_headers,
        )
        timeout = aiohttp.ClientTimeout(total=30)
        try:
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.post(
                    self.auth_config.token_url,
                    data=urlencode(body),
                    headers=headers,
                ) as response,
            ):
                raw = await response.text(encoding="utf-8")
                if response.status >= 400:
                    raise AuthRefreshError(f"刷新 token 请求失败: HTTP {response.status}")
        except aiohttp.ClientError as e:
            raise AuthRefreshError(f"刷新 token 请求失败: {e}") from e

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            raise AuthRefreshError("刷新 token 响应不是有效 JSON") from e

        token = payload.get(self.auth_config.token_field)
        if not token:
            raise AuthRefreshError(f"刷新 token 响应缺少字段: {self.auth_config.token_field}")

        self.auth_config.access_token = str(token)
        if refresh_token := payload.get("refresh_token"):
            self.auth_config.refresh_token = str(refresh_token)
        if expires_in := payload.get(self.auth_config.expires_in_field):
            self.auth_config.expires_at = time.time() + float(expires_in)
        return self.auth_config.access_token


def sanitize_auth_data(data: dict[str, Any] | None) -> dict[str, Any]:
    """清洗认证事件中的敏感字段。"""
    if not data:
        return {}
    sanitized: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in SENSITIVE_KEYS:
            sanitized[key] = "***"
        elif isinstance(value, dict):
            sanitized[key] = sanitize_auth_data(value)
        else:
            sanitized[key] = value
    return sanitized
