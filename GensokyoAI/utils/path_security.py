"""路径 ID 净化工具：防止路径遍历与文件系统注入。

用于把用户可控的标识符（角色名、session_id、外部工具源 ID 等）
转换为可安全用作文件/目录名的字符串。
"""

from __future__ import annotations

import re
import unicodedata


class PathSanitizationError(ValueError):
    """路径 ID 净化失败时抛出。"""

    def __init__(self, value: str, reason: str) -> None:
        super().__init__(f"无法净化路径标识符 {value!r}: {reason}")
        self.value = value
        self.reason = reason


# 安全字符集：
# - ASCII 字母、数字、下划线、连字符
# - CJK 统一表意文字（基本区与扩展 A）
# 其余字符统一替换为下划线，避免路径分隔符、控制字符、RTL 覆盖等攻击。
_SAFE_PATH_ID_PATTERN = re.compile(r"[A-Za-z0-9_\-一-鿿㐀-䶿]")


def sanitize_path_id(value: str, *, max_length: int = 64) -> str:
    """把任意字符串净化为可安全用于文件/目录名的标识符。

    规则：
    1. 仅保留安全字符（ASCII  alphanumeric / _ / - / CJK 汉字）。
    2. 连续非法字符压缩为单个下划线。
    3. 去除首尾下划线。
    4. 限制最大长度。
    5. 结果不能为空。

    Args:
        value: 原始标识符，例如角色名、session_id、source_id。
        max_length: 最大长度，默认 64。

    Returns:
        净化后的安全标识符。

    Raises:
        PathSanitizationError: 当结果为空或输入不是字符串时。
    """

    if not isinstance(value, str):
        raise PathSanitizationError(str(value), "输入必须是字符串")

    # NFC 规范化，避免组合字符绕过
    normalized = unicodedata.normalize("NFC", value)

    sanitized_chars: list[str] = []
    prev_was_underscore = False
    for char in normalized:
        if _SAFE_PATH_ID_PATTERN.fullmatch(char):
            sanitized_chars.append(char)
            prev_was_underscore = False
        else:
            if not prev_was_underscore:
                sanitized_chars.append("_")
                prev_was_underscore = True

    result = "".join(sanitized_chars).strip("_")

    if not result:
        raise PathSanitizationError(value, "净化后结果为空")

    if len(result) > max_length:
        result = result[:max_length].rstrip("_")
        if not result:
            raise PathSanitizationError(value, f"截断至 {max_length} 字符后为空")

    # 保留 . 和 .. 的检查：即使经过净化，也要避免产生保留目录名
    if result in {"", ".", ".."}:
        raise PathSanitizationError(value, "结果为保留路径名")

    return result


def sanitize_path_id_or_default(
    value: str,
    *,
    default: str,
    max_length: int = 64,
) -> str:
    """净化路径标识符；失败时返回 default 而不是抛出异常。"""

    try:
        return sanitize_path_id(value, max_length=max_length)
    except PathSanitizationError:
        return sanitize_path_id(default, max_length=max_length)


__all__ = [
    "PathSanitizationError",
    "sanitize_path_id",
    "sanitize_path_id_or_default",
]
