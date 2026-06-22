"""SSRF URL 安全校验测试。"""

from __future__ import annotations

import pytest

from GensokyoAI.utils.url_security import UnsafeUrlError, validate_external_url


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost/admin",
        "http://127.0.0.1/",
        "http://0.0.0.0/",
        "http://192.168.1.1/",
        "http://10.0.0.1/",
        "http://172.16.0.1/",
        "http://[::1]/",
        "ftp://public.example/file",
        "",
        "not-a-url",
    ],
)
def test_validate_external_url_rejects_unsafe(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        validate_external_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.openai.com/v1",
        "https://generativelanguage.googleapis.com/",
        "http://public.example.com:8080/path",
    ],
)
def test_validate_external_url_allows_public(url: str) -> None:
    validate_external_url(url)  # should not raise


def test_validate_external_url_allows_private_when_requested() -> None:
    validate_external_url("http://127.0.0.1:11434", allow_private=True)


def test_validate_external_url_rejects_metadata_even_when_private_allowed() -> None:
    with pytest.raises(UnsafeUrlError):
        validate_external_url("http://169.254.169.254/", allow_private=True)
