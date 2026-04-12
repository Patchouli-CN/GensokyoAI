"""格式化工具"""

# GenskoyoAI\utils\formatters.py

from datetime import datetime
from typing import Any


def format_session_id(session_id: str, length: int = 8) -> str:
    """格式化会话ID显示"""
    return f"{session_id[:length]}..."


def format_datetime(dt: datetime, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """格式化日期时间"""
    return dt.strftime(fmt)


def format_duration(seconds: float) -> str:
    """格式化时长"""
    if seconds < 60:
        return f"{seconds:.1f}秒"
    elif seconds < 3600:
        return f"{seconds / 60:.1f}分钟"
    else:
        return f"{seconds / 3600:.1f}小时"


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """截断文本"""
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix


def format_tool_result(result: Any, max_length: int = 200) -> str:
    """格式化工具执行结果"""
    if isinstance(result, str):
        return truncate_text(result, max_length)
    elif isinstance(result, (list, dict)):
        import json

        return truncate_text(json.dumps(result, ensure_ascii=False), max_length)
    else:
        return truncate_text(str(result), max_length)
