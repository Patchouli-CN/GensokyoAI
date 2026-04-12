"""工具执行器"""

# GenskoyoAI\tools\executor.py

import json
import asyncio

from ollama import Message

from .registry import ToolRegistry
from ..utils.logging import logger


class ToolExecutor:
    """工具执行器"""

    def __init__(self, registry: ToolRegistry | None = None):
        self._registry = registry or ToolRegistry()

    def parse_tool_calls(self, message: Message) -> list[dict]:
        """从 Message 对象解析工具调用"""
        if not message.tool_calls:
            return []
        
        parsed = []
        for tc in message.tool_calls:
            # ollama 的 Message.tool_calls 已经处理好了
            # tc.function.arguments 已经是 dict，不是字符串
            parsed.append({
                "name": tc.function.name,
                "arguments": tc.function.arguments,  # 直接是 dict
            })
        return parsed

    async def execute(self, tool_call: dict) -> dict:
        """执行单个工具调用"""
        name = tool_call.get("name")
        arguments = tool_call.get("arguments", {})

        tool_def = self._registry.get(name)  # type: ignore
        if not tool_def:
            error_msg = f"工具 '{name}' 未找到"
            logger.warning(error_msg)
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

            return {
                "role": "tool",
                "name": name,
                "content": result,
            }
        except Exception as e:
            error_msg = f"工具执行失败: {e}"
            logger.error(f"工具 {name} 执行错误: {e}")
            return {
                "role": "tool",
                "name": name,
                "content": f"错误: {error_msg}",
            }

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
