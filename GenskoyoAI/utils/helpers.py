"""通用辅助函数"""

# GenskoyoAI\utils\helpers.py

import asyncio
from typing import Any, Callable, Awaitable
from functools import wraps


def async_to_sync(func: Callable[..., Awaitable[Any]]):
    """将异步函数转换为同步函数"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))  # type: ignore

    return wrapper


def sync_to_async(func: Callable):
    """将同步函数转换为异步函数"""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    return wrapper


def retry_async(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
):
    """异步重试装饰器"""

    def decorator(func: Callable[..., Awaitable[Any]]):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff

            raise last_exception  # type: ignore

        return wrapper

    return decorator


def deep_merge(base: dict, override: dict) -> dict:
    """深度合并字典"""
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value

    return result


def safe_get(obj: Any, path: str, default: Any = None) -> Any:
    """安全获取嵌套属性"""
    try:
        for key in path.split("."):
            if isinstance(obj, dict):
                obj = obj.get(key, default)
            else:
                obj = getattr(obj, key, default)
            if obj is None:
                return default
        return obj
    except (AttributeError, KeyError, TypeError):
        return default
