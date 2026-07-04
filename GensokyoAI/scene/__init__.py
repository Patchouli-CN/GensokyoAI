# GensokyoAI/scene/__init__.py

"""场景管理 - 全局场景库、当前场景状态与异步切换。"""

from .manager import SceneError, SceneManager
from .types import Scene

__all__ = ["Scene", "SceneError", "SceneManager"]
