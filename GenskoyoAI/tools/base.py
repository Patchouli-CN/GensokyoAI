"""工具基类和装饰器"""

# GenskoyoAI\tools\base.py

import inspect
from typing import Callable, Any, Optional, get_type_hints
from msgspec import Struct
from enum import Enum


class ToolParameterType(Enum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"


class ToolParameter(Struct):
    """工具参数"""

    name: str
    type: ToolParameterType
    description: str = ""
    required: bool = True
    default: Any = None
    items: Optional[dict] = None  # for array type
    properties: Optional[dict] = None  # for object type


class ToolDefinition(Struct):
    """工具定义"""

    name: str
    description: str
    parameters: dict[str, ToolParameter]
    func: Callable
    is_async: bool = False

    def to_openai_schema(self) -> dict:
        """转换为 OpenAI 工具格式"""
        properties = {}
        required = []

        for name, param in self.parameters.items():
            prop = {"type": param.type.value, "description": param.description}
            if param.default is not None:
                prop["default"] = param.default
            if param.items:
                prop["items"] = param.items  # type: ignore
            if param.properties:
                prop["properties"] = param.properties  # type: ignore
            properties[name] = prop
            if param.required:
                required.append(name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


# 全局工具注册表（由 registry 管理）
_TOOL_REGISTRY: dict[str, ToolDefinition] = {}


def tool(name: Optional[str] = None, description: Optional[str] = None) -> Callable:
    """工具装饰器"""

    def decorator(func: Callable) -> Callable:
        tool_name = name or func.__name__
        tool_desc = description or (func.__doc__ or "").strip()

        # 解析参数
        sig = inspect.signature(func)
        type_hints = get_type_hints(func)
        parameters = {}

        for param_name, param in sig.parameters.items():
            param_type = type_hints.get(param_name, str)

            # 映射 Python 类型到 JSON Schema
            type_map = {
                str: ToolParameterType.STRING,
                int: ToolParameterType.INTEGER,
                float: ToolParameterType.NUMBER,
                bool: ToolParameterType.BOOLEAN,
                list: ToolParameterType.ARRAY,
                dict: ToolParameterType.OBJECT,
            }
            tool_type = type_map.get(param_type, ToolParameterType.STRING)

            parameters[param_name] = ToolParameter(
                name=param_name,
                type=tool_type,
                required=param.default is inspect.Parameter.empty,
                default=None
                if param.default is inspect.Parameter.empty
                else param.default,
            )

        # 检查是否是异步函数
        is_async = inspect.iscoroutinefunction(func)

        _TOOL_REGISTRY[tool_name] = ToolDefinition(
            name=tool_name,
            description=tool_desc,
            parameters=parameters,
            func=func,
            is_async=is_async,
        )

        return func

    return decorator


def get_tool(name: str) -> Optional[ToolDefinition]:
    """获取工具定义"""
    return _TOOL_REGISTRY.get(name)


def list_tools() -> dict[str, ToolDefinition]:
    """列出所有工具"""
    return _TOOL_REGISTRY.copy()
