"""工具执行器"""

# GensokyoAI\tools\executor.py

import asyncio
import json
from typing import TYPE_CHECKING, Any

from ..core.agent.types import UnifiedMessage
from ..runtime.event_contract import sanitize_event_payload
from ..utils.logger import logger
from .errors import ToolError, ToolExecutionError
from .external_manager import ExternalToolManager, is_external_tool_name
from .registry import ToolRegistry

if TYPE_CHECKING:
    from ..core.events import EventBus


class ToolExecutor:
    """工具执行器"""

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        event_bus: EventBus | None = None,
        external_tool_manager: ExternalToolManager | None = None,
    ):
        self._registry = registry or ToolRegistry()
        self._event_bus = event_bus
        self._external_tool_manager = external_tool_manager

    def set_event_bus(self, event_bus: EventBus) -> None:
        """注入事件总线"""
        self._event_bus = event_bus

    def set_external_tool_manager(self, manager: ExternalToolManager | None) -> None:
        """注入外部工具管理器。"""
        self._external_tool_manager = manager

    def parse_tool_calls(self, message: UnifiedMessage) -> list[dict[str, Any]]:
        """从 UnifiedMessage 对象解析工具调用"""
        if not message.tool_calls:
            return []

        parsed = []
        for tc in message.tool_calls:
            parsed.append(
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                }
            )
        return parsed

    async def execute(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        """执行单个工具调用"""
        name = tool_call.get("name")
        arguments = tool_call.get("arguments", {})

        if not name or not isinstance(name, str):
            error = ToolError(
                error_code="tool.invalid_name",
                technical_message=f"无效的工具名称: {name}",
                user_message="工具调用名称无效。",
                recoverable=True,
                action_hint="请检查模型输出的 tool call name 字段。",
                details={"name": name},
            )
            logger.error(error.technical_message)
            return self._error_result(
                tool_call, str(name) if name else "unknown", error, legacy_prefix="错误"
            )

        self._publish_tool_event("started", name, arguments)

        if is_external_tool_name(name):
            return await self._execute_external(tool_call, name, arguments)

        tool_def = self._registry.get(name)
        if not tool_def:
            error = ToolError(
                error_code="tool.not_found",
                technical_message=f"工具 '{name}' 未找到",
                user_message=f"工具“{name}”不可用。",
                recoverable=True,
                action_hint="请确认工具已注册，或从模型可用工具 schema 中移除该工具。",
                details={"name": name},
            )
            logger.warning(error.technical_message)
            self._publish_tool_event(
                "failed", name, arguments, error.technical_message, tool_error=error
            )
            return self._error_result(tool_call, name, error, legacy_prefix="调用出错啦")

        try:
            logger.debug(f"执行工具: {name}({arguments})")

            if tool_def.is_async:
                result = await tool_def.func(**arguments)
            else:
                result = await asyncio.to_thread(tool_def.func, **arguments)

            result = self._serialize_tool_result(result)

            logger.info(f"工具 {name} 执行成功: {result[:100]}...")
            self._publish_tool_event("completed", name, arguments, result=result)

            return {
                "role": "tool",
                "tool_call_id": tool_call.get("id", ""),
                "name": name,
                "content": result,
            }
        except ToolExecutionError as e:
            error = e.error
            logger.error(f"工具 {name} 执行错误: {error.technical_message}")
            self._publish_tool_event(
                "failed", name, arguments, error.technical_message, tool_error=error
            )
            return self._error_result(tool_call, name, error, legacy_prefix="错误")
        except Exception as e:
            error = ToolError(
                error_code="tool.execution_failed",
                technical_message=f"工具执行失败: {e}",
                user_message="工具执行失败。",
                recoverable=True,
                action_hint="请稍后重试；若持续失败，请检查工具配置和运行环境。",
                details={"name": name, "exception_type": type(e).__name__},
            )
            logger.error(f"工具 {name} 执行错误: {e}")
            self._publish_tool_event(
                "failed", name, arguments, error.technical_message, tool_error=error
            )
            return self._error_result(tool_call, name, error, legacy_prefix="错误")

    async def _execute_external(
        self,
        tool_call: dict[str, Any],
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if self._external_tool_manager is None:
            error = ToolError(
                error_code="external_tool.manager_unavailable",
                technical_message="External tool manager is not configured for ToolExecutor.",
                user_message="外部工具管理器不可用。",
                recoverable=True,
                action_hint="请确认 Runtime 或 Agent 已注入 ExternalToolManager。",
                details={"name": name},
            )
            logger.warning(error.technical_message)
            self._publish_tool_event(
                "failed", name, arguments, error.technical_message, tool_error=error
            )
            return self._error_result(tool_call, name, error, legacy_prefix="调用出错啦")

        try:
            result = await self._external_tool_manager.call_tool(name, arguments)
            result_content = self._serialize_tool_result(result)
            logger.info(f"外部工具 {name} 执行成功: {result_content[:100]}...")
            self._publish_tool_event("completed", name, arguments, result=result_content)
            return {
                "role": "tool",
                "tool_call_id": tool_call.get("id", ""),
                "name": name,
                "content": result_content,
            }
        except ToolExecutionError as e:
            error = e.error
            logger.error(f"外部工具 {name} 执行错误: {error.technical_message}")
            self._publish_tool_event(
                "failed", name, arguments, error.technical_message, tool_error=error
            )
            return self._error_result(tool_call, name, error, legacy_prefix="错误")
        except Exception as e:
            error = ToolError(
                error_code="external_tool.execution_failed",
                technical_message=f"外部工具执行失败: {e}",
                user_message="外部工具执行失败。",
                recoverable=True,
                action_hint="请检查外部工具源状态后重试。",
                details={"name": name, "exception_type": type(e).__name__},
            )
            logger.error(f"外部工具 {name} 执行错误: {e}")
            self._publish_tool_event(
                "failed", name, arguments, error.technical_message, tool_error=error
            )
            return self._error_result(tool_call, name, error, legacy_prefix="错误")

    @staticmethod
    def _serialize_tool_result(result: Any) -> str:
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)

    @staticmethod
    def _error_result(
        tool_call: dict[str, Any],
        name: str,
        error: ToolError,
        *,
        legacy_prefix: str,
    ) -> dict[str, Any]:
        """构造兼容旧字段的结构化错误结果。"""
        return {
            "role": "tool",
            "tool_call_id": tool_call.get("id", ""),
            "name": name,
            "content": f"{legacy_prefix}: {error.technical_message}",
            "is_error": True,
            "error": error.to_dict(),
        }

    def _publish_tool_event(
        self,
        status: str,
        name: str,
        arguments: dict[str, Any],
        error: str | None = None,
        result: str | None = None,
        tool_error: ToolError | None = None,
    ) -> None:
        """发布工具事件"""
        if self._event_bus is None:
            return

        from ..core.events import Event, SystemEvent

        if status == "started":
            event_type = SystemEvent.TOOL_CALL_STARTED
        elif status == "progress":
            event_type = SystemEvent.TOOL_CALL_PROGRESS
        elif status == "completed":
            event_type = SystemEvent.TOOL_CALL_COMPLETED
        else:
            event_type = SystemEvent.TOOL_CALL_FAILED

        data: dict[str, Any] = {
            "name": name,
            "arguments": sanitize_event_payload(arguments),
            "external": is_external_tool_name(name),
        }
        if error:
            data["error"] = error
        if tool_error:
            data.update(
                {
                    "error_code": tool_error.error_code,
                    "user_message": tool_error.user_message,
                    "technical_message": tool_error.technical_message,
                    "recoverable": tool_error.recoverable,
                    "action_hint": tool_error.action_hint,
                    "details": dict(tool_error.details),
                }
            )
        if result:
            data["result"] = result[:200] if len(result) > 200 else result

        self._event_bus.publish(
            Event(
                type=event_type,
                source="tool_executor",
                data=sanitize_event_payload(data),
            )
        )

    def publish_progress(
        self,
        name: str,
        status: str,
        *,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """发布工具调用进度事件，供长耗时工具或外部工具适配器复用。"""
        payload: dict[str, Any] = {"status": status}
        if message:
            payload["message"] = message
        if details:
            payload["details"] = details
        self._publish_tool_event("progress", name, payload)

    async def execute_batch(self, tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """批量执行工具调用（并行）"""
        tasks = [self.execute(tc) for tc in tool_calls]
        results = await asyncio.gather(*tasks)
        return results

    def execute_sync(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        """同步执行（兼容非异步环境）"""
        name = tool_call.get("name")
        arguments = tool_call.get("arguments", {})

        if not name or not isinstance(name, str):
            error = ToolError(
                error_code="tool.invalid_name",
                technical_message=f"无效的工具名称: {name}",
                user_message="工具调用名称无效。",
                recoverable=True,
                action_hint="请检查模型输出的 tool call name 字段。",
                details={"name": name},
            )
            logger.error(error.technical_message)
            return self._error_result(
                tool_call, str(name) if name else "unknown", error, legacy_prefix="错误"
            )

        if is_external_tool_name(name):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(self.execute(tool_call))
            error = ToolError(
                error_code="external_tool.sync_not_supported",
                technical_message="External tools require async execution when an event loop is already running.",
                user_message="外部工具不支持当前同步调用方式。",
                recoverable=True,
                action_hint="请改用异步 execute() 调用外部工具。",
                details={"name": name},
            )
            return self._error_result(tool_call, name, error, legacy_prefix="错误")

        tool_def = self._registry.get(name)
        if not tool_def:
            error = ToolError(
                error_code="tool.not_found",
                technical_message=f"工具 '{name}' 未找到",
                user_message=f"工具“{name}”不可用。",
                recoverable=True,
                action_hint="请确认工具已注册，或从模型可用工具 schema 中移除该工具。",
                details={"name": name},
            )
            return self._error_result(tool_call, name, error, legacy_prefix="错误")

        try:
            result = tool_def.func(**arguments)
            result_content = self._serialize_tool_result(result)
            return {
                "role": "tool",
                "tool_call_id": tool_call.get("id", ""),
                "name": name,
                "content": result_content,
            }
        except ToolExecutionError as e:
            return self._error_result(tool_call, name, e.error, legacy_prefix="错误")
        except Exception as e:
            error = ToolError(
                error_code="tool.execution_failed",
                technical_message=f"工具执行失败: {e}",
                user_message="工具执行失败。",
                recoverable=True,
                action_hint="请稍后重试；若持续失败，请检查工具配置和运行环境。",
                details={"name": name, "exception_type": type(e).__name__},
            )
            return self._error_result(tool_call, name, error, legacy_prefix="错误")
