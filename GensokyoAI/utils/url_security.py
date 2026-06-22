"""URL 安全校验工具：防止 SSRF 等通过用户可控 URL 访问内网或元数据服务。"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeUrlError(ValueError):
    """URL 未通过安全校验时抛出。"""

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"不安全的 URL {url!r}: {reason}")
        self.url = url
        self.reason = reason


# 明确禁止的主机名（大小写不敏感）：元数据、通配符、空主机名永远不允许
_ALWAYS_FORBIDDEN_HOSTNAMES = frozenset(
    {
        "169.254.169.254",  # AWS / 云厂商 metadata
        "metadata.google.internal",
        "metadata",
        "*",
        "",
    }
)

# 回环主机名：默认禁止，但 allow_private=True 时可放行（本地 Ollama 场景）
_LOOPBACK_HOSTNAMES = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::",
        "::1",
    }
)

# 永远禁止解析到的网段：链路本地 / 元数据 / 0.0.0.0
_ALWAYS_FORBIDDEN_NETWORKS = frozenset(
    {
        ipaddress.ip_network("0.0.0.0/8"),
        ipaddress.ip_network("169.254.0.0/16"),
        ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
    }
)

# 回环网段：默认禁止，allow_private=True 时可放行
_LOOPBACK_NETWORKS = frozenset(
    {
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("::1/128"),
    }
)

# 私有网段：默认禁止，allow_private=True 时可放行
_PRIVATE_NETWORKS = frozenset(
    {
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("100.64.0.0/10"),  # CGNAT
        ipaddress.ip_network("fc00::/7"),  # IPv6 ULA
    }
)


_ALL_FORBIDDEN_NETWORKS = _ALWAYS_FORBIDDEN_NETWORKS | _LOOPBACK_NETWORKS | _PRIVATE_NETWORKS


def _is_private_ip(host: str) -> bool:
    """判断主机名是否为私有网段 IP。"""

    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False

    return any(addr in network for network in _PRIVATE_NETWORKS)


def _is_loopback_ip(host: str) -> bool:
    """判断主机名是否为回环 IP。"""

    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False

    return any(addr in network for network in _LOOPBACK_NETWORKS)


def _is_always_forbidden_ip(host: str) -> bool:
    """判断主机名是否为永远禁止的 IP（链路本地、元数据、0.0.0.0）。"""

    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False

    return any(addr in network for network in _ALWAYS_FORBIDDEN_NETWORKS)


def _hostname_is_forbidden(hostname: str) -> bool:
    """判断主机名是否在显式禁止列表中或为禁止 IP。"""

    if not hostname:
        return True
    lower = hostname.lower()
    if lower in _ALWAYS_FORBIDDEN_HOSTNAMES:
        return True
    if lower.startswith("169.254."):
        return True
    return (
        _is_always_forbidden_ip(hostname) or _is_private_ip(hostname) or _is_loopback_ip(hostname)
    )


def validate_external_url(
    url: str,
    *,
    allow_private: bool = False,
    resolve_dns: bool = False,
) -> None:
    """校验外部 URL 是否安全。

    默认禁止：
    - 非 http/https 协议
    - localhost / 127.0.0.1 / 0.0.0.0 / ::1 等回环地址
    - 私有网段（10/8、172.16/12、192.168/16 等）
    - 链路本地 / 元数据服务（169.254.169.254）
    - 空主机名或通配符

    Args:
        url: 待校验 URL。
        allow_private: 若为 True，则允许私有 IP（但仍禁止元数据和回环）。
            用于本地 Ollama 等场景。
        resolve_dns: 是否解析域名并检查解析结果。默认 False，避免在配置校验
            等路径引入网络调用；开启后可防御"域名指向内网"场景。

    Raises:
        UnsafeUrlError: 校验失败。
    """

    if not isinstance(url, str) or not url:
        raise UnsafeUrlError(str(url), "URL 不能为空")

    # 去除首尾空白，防御简单绕过
    url = url.strip()
    parsed = urlparse(url)

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise UnsafeUrlError(url, f"不支持的协议: {scheme!r}")

    hostname = parsed.hostname
    if hostname is None:
        raise UnsafeUrlError(url, "无法解析主机名")

    hostname_lower = hostname.lower()
    if hostname_lower in _ALWAYS_FORBIDDEN_HOSTNAMES:
        raise UnsafeUrlError(url, f"禁止的主机名: {hostname!r}")

    if not allow_private and (hostname_lower in _LOOPBACK_HOSTNAMES or _is_loopback_ip(hostname)):
        raise UnsafeUrlError(url, f"禁止的回环主机名: {hostname!r}")

    if _is_always_forbidden_ip(hostname):
        raise UnsafeUrlError(url, f"禁止的 IP 地址: {hostname!r}")

    if not allow_private and _is_private_ip(hostname):
        raise UnsafeUrlError(url, f"禁止的私有 IP 地址: {hostname!r}")

    if resolve_dns and not _is_always_forbidden_ip(hostname):
        try:
            resolved = socket.getaddrinfo(hostname, None)
            addresses = {str(item[4][0]) for item in resolved}
            for addr in addresses:
                if _is_always_forbidden_ip(addr):
                    raise UnsafeUrlError(url, f"域名解析到禁止地址: {addr!r}")
                if not allow_private and (_is_loopback_ip(addr) or _is_private_ip(addr)):
                    raise UnsafeUrlError(url, f"域名解析到非安全地址: {addr!r}")
        except UnsafeUrlError:
            raise
        except Exception:
            # DNS 解析失败时保守拒绝
            raise UnsafeUrlError(url, "无法解析域名或解析到非安全地址") from None


def is_safe_public_url(url: str) -> bool:
    """安全返回 bool 的便捷封装。"""

    try:
        validate_external_url(url)
        return True
    except UnsafeUrlError:
        return False


__all__ = [
    "UnsafeUrlError",
    "is_safe_public_url",
    "validate_external_url",
]
