"""工具执行器"""

# GensokyoAI\tools\executor.py

import json
import asyncio
from typing import TYPE_CHECKING, Optional

from ollama import Message

from .registry import ToolRegistry
from ..utils.logging import logger

if TYPE_CHECKING:
    from ..core.events import EventBus


class ToolExecutor:
    """工具执行器"""

    def __init__(self, registry: ToolRegistry | None = None, event_bus: Optional["EventBus"] = None):
        self._registry = registry or ToolRegistry()
        self._event_bus = event_bus

    def set_event_bus(self, event_bus: "EventBus") -> None:
        """注入事件总线"""
        self._event_bus = event_bus

    def parse_tool_calls(self, message: Message) -> list[dict]:
        """从 Message 对象解析工具调用"""
        if not message.tool_calls:
            return []

        parsed = []
        for tc in message.tool_calls:
            parsed.append(
                {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                }
            )
        return parsed

    async def execute(self, tool_call: dict) -> dict:
        """执行单个工具调用"""
        name = tool_call.get("name")
        arguments = tool_call.get("arguments", {})

        # 🆕 发布工具调用开始事件
        self._publish_tool_event("started", name, arguments)

        tool_def = self._registry.get(name)  # type: ignore
        if not tool_def:
            error_msg = f"工具 '{name}' 未找到"
            logger.warning(error_msg)
            # 🆕 发布工具调用失败事件
            self._publish_tool_event("failed", name, arguments, error_msg)
            return {
                "role": "tool",
                "name": name,
                "content": f"调用出错啦: {error_msg}",
            }

        try:
            logger.debug(f"执行工具: {name}({arguments})")

            if tool_def.is_async:
                result = await tool_def.func(**arguments)
            else:
                # 同步函数在线程池中执行
                result = await asyncio.to_thread(tool_def.func, **arguments)

            # 转换结果为字符串
            if not isinstance(result, str):
                result = json.dumps(result, ensure_ascii=False)

            logger.info(f"工具 {name} 执行成功: {result[:100]}...")

            # 🆕 发布工具调用完成事件
            self._publish_tool_event("completed", name, arguments, result=result)

            return {
                "role": "tool",
                "name": name,
                "content": result,
            }
        except Exception as e:
            error_msg = f"工具执行失败: {e}"
            logger.error(f"工具 {name} 执行错误: {e}")
            # 🆕 发布工具调用失败事件
            self._publish_tool_event("failed", name, arguments, error_msg)
            return {
                "role": "tool",
                "name": name,
                "content": f"错误: {error_msg}",
            }

    def _publish_tool_event(
        self,
        status: str,
        name: str,
        arguments: dict,
        error: str | None = None,
        result: str | None = None,
    ) -> None:
        """发布工具事件"""
        if self._event_bus is None:
            return

        from ..core.events import Event, SystemEvent

        if status == "started":
            event_type = SystemEvent.TOOL_CALL_STARTED
        elif status == "completed":
            event_type = SystemEvent.TOOL_CALL_COMPLETED
        else:
            event_type = SystemEvent.TOOL_CALL_FAILED

        data = {
            "name": name,
            "arguments": arguments,
        }
        if error:
            data["error"] = error
        if result:
            data["result"] = result[:200] if len(result) > 200 else result

        self._event_bus.publish(
            Event(
                type=event_type,
                source="tool_executor",
                data=data,
            )
        )

    async def execute_batch(self, tool_calls: list[dict]) -> list[dict]:
        """批量执行工具调用（并行）"""
        tasks = [self.execute(tc) for tc in tool_calls]
        results = await asyncio.gather(*tasks)
        return results

    def execute_sync(self, tool_call: dict) -> dict:
        """同步执行（兼容非异步环境）"""
        name = tool_call.get("name")
        arguments = tool_call.get("arguments", {})

        tool_def = self._registry.get(name)  # type: ignore
        if not tool_def:
            return {
                "role": "tool",
                "name": name,
                "content": f"错误: 工具 '{name}' 未找到",
            }

        try:
            result = tool_def.func(**arguments)
            if not isinstance(result, str):
                result = json.dumps(result, ensure_ascii=False)
            return {
                "role": "tool",
                "name": name,
                "content": result,
            }
        except Exception as e:
            return {
                "role": "tool",
                "name": name,
                "content": f"错误: {e}",
            }