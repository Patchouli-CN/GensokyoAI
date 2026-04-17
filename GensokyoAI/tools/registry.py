"""工具注册中心"""

# GensokyoAI\tools\registry.py

import importlib
import importlib.util
import pkgutil
from pathlib import Path
from typing import Optional, Callable

from .base import ToolDefinition, list_tools, get_tool, tool
from ..utils.logging import logger


class ToolRegistry:
    """工具注册中心"""

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._load_builtin()

    def _load_builtin(self) -> None:
        """自动发现并加载内置工具"""

        builtin_dir = Path(__file__).parent / "tool_builtin"
        for py_file in builtin_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            module_name = py_file.stem
            try:
                importlib.import_module(f".tool_builtin.{module_name}", package=__package__)
                logger.debug(f"加载内置工具: {module_name}")
            except Exception as e:
                logger.warning(f"加载 {module_name} 失败: {e}")

        self._tools.update(list_tools())

    def register(self, func: Callable, name: Optional[str] = None) -> None:
        """注册工具（非装饰器方式）"""

        decorated = tool(name=name)(func)
        self._tools[decorated.name] = decorated

    def register_module(self, module_path: Path) -> None:
        """注册模块中的所有工具"""
        spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            logger.debug(f"加载模块: {module_path}")

    def register_package(self, package_path: Path) -> None:
        """注册包中的所有工具"""
        for _, name, _ in pkgutil.iter_modules([str(package_path)]):
            try:
                importlib.import_module(f"tools.builtin.{name}")
            except ImportError as e:
                logger.warning(f"导入模块 {name} 失败: {e}")

    def get(self, name: str) -> Optional[ToolDefinition]:
        """获取工具"""
        return self._tools.get(name) or get_tool(name)

    def list(self) -> list[ToolDefinition]:
        """列出所有工具"""
        return list(self._tools.values())

    def get_schemas(self) -> list[dict]:
        """获取所有工具的 OpenAI schema"""
        return [tool.to_openai_schema() for tool in self._tools.values()]

    def unregister(self, name: str) -> bool:
        """注销工具"""
        if name in self._tools:
            del self._tools[name]
            return True
        return False
