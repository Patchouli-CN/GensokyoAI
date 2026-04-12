"""时间工具"""

# GenskoyoAI\tools\tool_builtin\time.py

from datetime import datetime
from ..base import tool


@tool(description="获取当前时间（小时:分钟:秒）")
def get_current_time() -> str:
    """获取当前本地时间，只返回小时分钟和秒"""
    return datetime.now().strftime("%H:%M:%S")


@tool(description="获取当前日期信息，包括星期和曜日")
def get_current_dateinfo() -> str:
    """获取当前详细的时间信息，包括星期几和七曜日"""
    now = datetime.now()
    weekday = now.weekday()  # 0=周一
    weekday_str = "一二三四五六日"[weekday]
    seven_luminaries = "月火水木金土日"[weekday]
    return now.strftime("%Y-%m-%d") + f", 星期{weekday_str} | {seven_luminaries}曜日"
