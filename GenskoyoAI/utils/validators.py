"""验证工具"""

# GenskoyoAI\utils\validators.py

from pathlib import Path
from typing import Any


def validate_path(path: str | Path) -> Path:
    """验证并返回Path对象"""
    if isinstance(path, str):
        path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"路径不存在: {path}")

    return path


def validate_config_value(value: Any, allowed_values: list[Any] | None = None) -> bool:
    """验证配置值"""
    if allowed_values is not None:
        return value in allowed_values
    return True


def validate_model_name(name: str) -> bool:
    """验证模型名称格式"""
    return bool(name and isinstance(name, str) and len(name) > 0)


def validate_temperature(value: float) -> bool:
    """验证温度参数"""
    return 0.0 <= value <= 2.0


def validate_top_p(value: float) -> bool:
    """验证top_p参数"""
    return 0.0 <= value <= 1.0
