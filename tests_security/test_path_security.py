"""路径 ID 净化相关测试。"""

from __future__ import annotations

import pytest

from GensokyoAI.utils.path_security import (
    PathSanitizationError,
    sanitize_path_id,
    sanitize_path_id_or_default,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../../etc/passwd", "etc_passwd"),
        ("..\\..\\Windows\\System32\\config", "Windows_System32_config"),
        ("normal_session_id", "normal_session_id"),
        ("雾雨魔理沙", "雾雨魔理沙"),
        ("Reimu-Hakurei_001", "Reimu-Hakurei_001"),
        ("a/b/c", "a_b_c"),
        ("name\x00with\x01ctrl", "name_with_ctrl"),
        ("  spaced  ", "spaced"),
    ],
)
def test_sanitize_path_id(raw: str, expected: str) -> None:
    assert sanitize_path_id(raw) == expected


def test_sanitize_path_id_rejects_empty() -> None:
    with pytest.raises(PathSanitizationError):
        sanitize_path_id("....////")


def test_sanitize_path_id_rejects_non_string() -> None:
    with pytest.raises(PathSanitizationError):
        sanitize_path_id(None)  # type: ignore[arg-type]


def test_sanitize_path_id_enforces_max_length() -> None:
    long_name = "a" * 100
    assert len(sanitize_path_id(long_name, max_length=10)) == 10


def test_sanitize_path_id_or_default_fallback() -> None:
    assert sanitize_path_id_or_default("....", default="fallback") == "fallback"
