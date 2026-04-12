"""日志实现 - 支持动态配置"""

# GenskoyoAI\utils\logging.py

import sys
from pathlib import Path
from typing import Optional

from loguru import logger

# 移除默认配置
logger.remove()

# 保存 handler IDs 以便后续管理
_handlers = {"console": None, "file": None}

# 默认不添加任何 handler
# 等待应用配置加载后再设置


def setup_logging(
    log_level: str = "INFO",
    log_console: bool = True,
    log_file: Optional[Path] = None,
    log_format: Optional[str] = None,
    log_format_console: Optional[str] = None,
) -> None:
    """配置日志系统

    Args:
        log_level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_console: 是否输出到控制台
        log_file: 日志文件路径
        log_format: 文件日志格式
        log_format_console: 控制台日志格式
    """
    global _handlers

    # 移除现有 handlers
    if _handlers["console"] is not None:
        logger.remove(_handlers["console"])
        _handlers["console"] = None
    if _handlers["file"] is not None:
        logger.remove(_handlers["file"])
        _handlers["file"] = None

    # 默认格式
    if log_format is None:
        log_format = "[{thread.name:^12}] {time:HH:mm:ss} | {level:<8} | {name}.{function}:{line:03d} | {message}"

    if log_format_console is None:
        log_format_console = "<level>[{thread.name:^12}] {time:HH:mm:ss} | {level:<8} | {name}.{function}:{line:03d} | {message}</level>"

    # 添加控制台 handler
    if log_console:
        _handlers["console"] = logger.add(  # type: ignore
            sys.stderr,
            format=log_format_console,
            level=log_level,
            colorize=True,
        )

    # 添加文件 handler
    if log_file is not None:
        # 确保日志目录存在
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)

        _handlers["file"] = logger.add(  # type: ignore
            str(log_file),
            format=log_format,
            level=log_level,
            rotation="10 MB",
            compression="zip",
            backtrace=True,
            diagnose=True,
            enqueue=True,
        )


def get_logger():
    """获取 logger 实例"""
    return logger


# 为了兼容性，保留原有的 logger 导出
__all__ = ["logger", "setup_logging", "get_logger"]


# 测试代码
if __name__ == "__main__":
    # 测试控制台日志
    setup_logging(log_level="DEBUG", log_console=True)
    logger.trace("这是一个 trace 级别的日志")
    logger.debug("这是一个 debug 级别的日志")
    logger.info("这是一个 info 级别的日志")
    logger.success("这是一个 success 级别的日志")
    logger.warning("这是一个 warning 级别的日志")
    logger.error("这是一个 error 级别的日志")
    logger.critical("这是一个 critical 级别的日志")

    # 测试文件日志
    setup_logging(log_level="INFO", log_console=False, log_file=Path("logs/test.log"))
    logger.info("这条日志只写入文件")
