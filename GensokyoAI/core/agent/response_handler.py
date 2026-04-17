"""响应处理器 - 处理模型响应和工具调用"""

# GensokyoAI/core/agent/response_handler.py

from typing import AsyncIterator, TYPE_CHECKING

from ollama import Message, ChatResponse

from .model_client import StreamChunk
from ...utils.logging import logger
from ...utils.helpers import safe_get
from ...memory.types import MemoryRecord

if TYPE_CHECKING:
    from ...memory.working import WorkingMemoryManager
    from ...memory.episodic import EpisodicMemoryManager
    from ...tools.executor import ToolExecutor
    from ...core.config import AppConfig
    from .model_client import ModelClient
    from .message_builder import MessageBuilder
    from .save_coordinator import SaveCoordinator
    from ...background import BackgroundManager


class ResponseHandler:
    """
    响应处理器 - 处理模型响应和后续操作

    职责：
    - 处理工具调用
    - 记录用户/工具消息（助手消息由事件监听器记录）
    - 触发自动记忆
    - 协调流式和非流式响应
    """

    def __init__(
        self,
        config: "AppConfig",
        working_memory: "WorkingMemoryManager",
        episodic_memory: "EpisodicMemoryManager",
        tool_executor: "ToolExecutor",
        model_client: "ModelClient",
        message_builder: "MessageBuilder",
        save_coordinator: "SaveCoordinator",
    ):
        """
        初始化响应处理器

        Args:
            config: 应用配置
            working_memory: 工作记忆管理器
            episodic_memory: 情景记忆管理器
            tool_executor: 工具执行器
            model_client: 模型客户端
            message_builder: 消息构建器
            save_coordinator: 保存协调器
        """
        self._config = config
        self._working_memory = working_memory
        self._episodic_memory = episodic_memory
        self._tool_executor = tool_executor
        self._model_client = model_client
        self._message_builder = message_builder
        self._save_coordinator = save_coordinator

        # 后台管理器引用（用于自动记忆）
        self._background_manager: "BackgroundManager | None" = None

        # 关闭状态
        self._shutting_down = False

    def set_background_manager(self, manager: "BackgroundManager") -> None:
        """注入后台管理器"""
        self._background_manager = manager

    def set_shutting_down(self, value: bool) -> None:
        """设置关闭状态"""
        self._shutting_down = value

    @property
    def character_name(self) -> str:
        """获取角色名称"""
        return safe_get(self._config, "character.name", "default")

    # ==================== 消息记录 ====================

    def record_user_message(self, content: str) -> None:
        """记录用户消息"""
        self._working_memory.add_message("user", content)
        self._episodic_memory.add_message(
            MemoryRecord(
                content=content,
                role="user",
                character_id=self.character_name,
            )
        )

    def record_assistant_message(self, msg: str) -> None:
        """记录助手消息（带去重保护）- 注意：此方法已废弃，助手消息由事件监听器记录"""
        if not msg:
            return

        wm = self._working_memory

        # 去重检查
        if wm._memory.messages:
            last_msg = wm._memory.messages[-1]
            if last_msg["role"] == "assistant" and last_msg["content"] == msg:
                logger.debug("跳过重复的助手消息记录")
                return

        self._working_memory.add_message("assistant", msg)
        self._episodic_memory.add_message(
            MemoryRecord(
                content=msg,
                role="assistant",
                character_id=self.character_name,
            )
        )

    def record_tool_results(self, results: list[dict]) -> None:
        """记录工具调用结果"""
        for result in results:
            self._working_memory.add_message(result["role"], result["content"])
            self._episodic_memory.add_message(
                MemoryRecord(
                    content=result["content"],
                    role="tool",
                    character_id=self.character_name,
                    metadata={"tool_name": result.get("name", "")},
                )
            )

    # ==================== 工具处理 ====================

    async def handle_tool_calls_from_message(self, message: Message) -> list[dict] | None:
        """
        从 Message 对象处理工具调用

        Args:
            message: 包含 tool_calls 的 Message 对象

        Returns:
            工具执行结果列表，如果没有工具调用则返回 None
        """
        if not message.tool_calls:
            return None

        logger.info(f"检测到 {len(message.tool_calls)} 个工具调用")

        if parsed_calls := self._tool_executor.parse_tool_calls(message):
            return await self._tool_executor.execute_batch(parsed_calls)

        return None

    async def handle_tool_calls_from_response(self, response: ChatResponse) -> list[dict] | None:
        """
        从 ChatResponse 对象处理工具调用（便捷方法）

        Args:
            response: ChatResponse 对象

        Returns:
            工具执行结果列表
        """
        return await self.handle_tool_calls_from_message(response.message)

    async def handle_tool_chain(
        self, partial_message: Message, tool_results: list[dict]
    ) -> Message:
        """
        处理工具调用链，返回完整响应

        Args:
            partial_message: 包含部分内容和工具调用的 Message
            tool_results: 工具执行结果

        Returns:
            完整的助手消息
        """
        result = partial_message.content or ""
        self.record_tool_results(tool_results)

        if partial_message.content:
            self._working_memory.add_message("assistant", result)

        continuation = await self._continue_with_tool_results()
        final_content = result + continuation

        return Message(role="assistant", content=final_content)

    async def _continue_with_tool_results(self) -> str:
        """带着工具结果继续对话"""
        messages = self._message_builder.build_continuation()
        response = await self._model_client.chat(messages, None)
        return response.message.content or ""

    async def _continue_with_tool_results_stream(self) -> AsyncIterator[StreamChunk]:
        """带着工具结果继续对话 - 流式版本"""
        messages = self._message_builder.build_continuation()
        async for chunk in self._model_client.chat_stream(messages, None):
            yield chunk

    # ==================== 自动记忆 ====================

    def _should_auto_memory(self, user_input: str, assistant_response: str) -> bool:
        """判断是否需要自动记忆"""
        if not self._config.memory.auto_memory_enabled:
            return False

        if self._shutting_down:
            return False

        # 快速预判
        if len(user_input) < 20 and len(assistant_response) < 50:
            return False

        return True

    async def trigger_auto_memory(self, user_input: str, assistant_response: str) -> None:
        """触发异步自动记忆"""
        if not self._should_auto_memory(user_input, assistant_response):
            return

        if self._background_manager is None:
            logger.warning("后台管理器未注入，无法提交自动记忆任务")
            return

        from ...background import TaskPriority

        self._background_manager.submit_memory_task(
            user_input=user_input,
            assistant_response=assistant_response,
            priority=TaskPriority.LOW,
            timeout=5.0,
        )

    # ==================== 响应处理 ====================

    async def process_non_stream(
        self,
        user_input: str,
        messages: list[dict[str, str]],
        tools: list[dict] | None,
    ) -> Message:
        """
        处理非流式响应

        Args:
            user_input: 用户输入（用于自动记忆）
            messages: 消息列表
            tools: 工具 schema 列表

        Returns:
            最终的助手消息
        """
        response = await self._model_client.chat(messages, tools)
        message = response.message

        # 处理工具调用
        if tool_results := await self.handle_tool_calls_from_message(message):
            message = await self.handle_tool_chain(message, tool_results)

        # 触发自动记忆（助手消息由事件监听器记录）
        if message.content:
            await self.trigger_auto_memory(user_input, message.content)

        await self._save_coordinator.save_async(self._working_memory)

        return message

    async def process_stream(
        self,
        user_input: str,
        messages: list[dict[str, str]],
        tools: list[dict] | None,
    ) -> AsyncIterator[StreamChunk]:
        """
        处理流式响应

        Args:
            user_input: 用户输入
            messages: 消息列表
            tools: 工具 schema 列表

        Yields:
            StreamChunk: 流式响应块
        """
        full_content = ""
        tool_calls_message: Message | None = None

        # 第一轮：获取初始响应
        async for chunk in self._model_client.chat_stream(messages, tools):
            if self._shutting_down:
                break
            if chunk.is_tool_call and chunk.tool_info:
                tool_calls_message = chunk.tool_info["message"]
            else:
                full_content += chunk.content
            yield chunk

        if self._shutting_down:
            return

        # 处理工具调用
        if tool_calls_message:
            if tool_results := await self.handle_tool_calls_from_message(tool_calls_message):
                self.record_tool_results(tool_results)

                # 继续对话
                async for chunk in self._continue_with_tool_results_stream():
                    if self._shutting_down:
                        break
                    full_content += chunk.content
                    yield chunk

        # 触发自动记忆（助手消息由事件监听器记录）
        if full_content and not self._shutting_down:
            await self.trigger_auto_memory(user_input, full_content)

        await self._save_coordinator.save_async(self._working_memory)
