"""工具模块"""

# GensokyoAI\utils\__init__.py

from .logging import logger, setup_logging
from .exec_hook import set_exechook
from .formatters import (
    format_session_id,
    format_datetime,
    format_duration,
    truncate_text,
    format_tool_result,
)
from .helpers import (
    async_to_sync,
    sync_to_async,
    retry_async,
    deep_merge,
    safe_get,
)

__all__ = [
    # logging
    "logger",
    "setup_logging",
    # exec_hook
    "set_exechook",
    # formatters
    "format_session_id",
    "format_datetime",
    "format_duration",
    "truncate_text",
    "format_tool_result",
    # helpers
    "async_to_sync",
    "sync_to_async",
    "retry_async",
    "deep_merge",
    "safe_get",
]
