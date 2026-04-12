"""月相工具"""

# GenskoyoAI\tools\tool_builtin\moon.py

from datetime import datetime, timedelta
from ..base import tool


@tool(description="获取月相，可以指定偏移天数（正数为未来，负数为过去）")
def get_moon_phase(days_delta: int = 0) -> str:
    """
    获取指定日期的月相

    Args:
        days_delta: 相对于今天的偏移天数，0表示今天
    """
    base = datetime.now() + timedelta(days=days_delta)
    # 简化的月相计算（基于日期）
    # 更精确的实现可以使用天文算法
    day = base.day % 8
    phases = ["新月", "峨眉月", "上弦月", "盈凸月", "满月", "亏凸月", "下弦月", "残月"]
    return phases[day]
