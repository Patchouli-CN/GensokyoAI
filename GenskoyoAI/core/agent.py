"""Agent 主类 - 异步优化版"""

from typing import AsyncIterator
from pathlib import Path
import asyncio
import signal
import sys
from contextvars import ContextVar
from uuid import uuid4

import ollama
from ollama import Message, ChatResponse
from msgspec import Struct

from .config import AppConfig, ConfigLoader
from .events import EventBus
from .exceptions import AgentError, ModelError
from ..memory.working import WorkingMemoryManager
from ..memory.episodic import EpisodicMemoryManager
from ..memory.semantic import SemanticMemoryManager
from ..memory.types import MemoryRecord
from ..tools.registry import ToolRegistry
from ..tools.executor import ToolExecutor
from ..session.manager import SessionManager
from ..session.context import SessionContext
from ..utils.logging import logger
from ..utils.helpers import safe_get, sync_to_async
from ..background import (
    BackgroundManager,
    TaskResult,
    MemoryWorker,
    PersistenceWorker,
    TaskPriority,
)

# 请求上下文
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    """获取当前请求ID"""
    rid = request_id_var.get()
    if not rid:
        rid = str(uuid4())[:8]
        request_id_var.set(rid)
    return rid


class StreamChunk(Struct):
    """流式响应块"""

    content: str = ""
    is_tool_call: bool = False
    tool_info: dict | None = None


class Agent:
    """AI 角色扮演 Agent - 只负责模型交互，不负责输出展示"""

    def __init__(
        self,
        config: AppConfig | None = None,
        config_file: Path | None = None,
        character_file: Path | None = None,
    ):
        # 加载配置
        loader = ConfigLoader()
        self.config = config or loader.load(config_file)

        # 加载角色
        if character_file:
            self.config.character = loader.load_character(character_file)
        elif self.config.character_file:
            self.config.character = loader.load_character(self.config.character_file)

        if not self.config.character:
            raise AgentError("No character loaded")

        # 初始化事件总线
        self.event_bus = EventBus()

        self._working_memory: WorkingMemoryManager | None = None

        # 初始化会话管理
        character_name = safe_get(self.config, "character.name", "default")
        self.session_manager = SessionManager(self.config.session, character_name)

        # 初始化记忆系统
        base_path = self.config.session.save_path / "memory"

        self.episodic_memory = EpisodicMemoryManager(
            self.config.memory,
            character_name,
            None,
        )
        self.semantic_memory = SemanticMemoryManager(
            self.config.memory, character_name, base_path
        )

        # 初始化工具系统
        self.tool_registry = ToolRegistry()
        self.tool_executor = ToolExecutor(self.tool_registry)
        self._current_response = ""

        # 创建异步版本的 ollama 调用
        self._ollama_chat_async = sync_to_async(ollama.chat)

        # 初始化后台管理器
        self._background_manager: BackgroundManager | None = None
        self._bg_task: asyncio.Task | None = None

        # 去重标记：避免重复保存
        self._save_pending = False
        self._last_saved_turn = 0

        # 关闭状态
        self._shutting_down = False
        self._shutdown_event = asyncio.Event()

        # 请求管理
        self._active_request_lock = asyncio.Lock()
        self._current_task: asyncio.Task | None = None
        self._request_semaphore = asyncio.Semaphore(1)  # 限制并发请求

        self._setup()
        self._setup_signal_handlers()

    # ==================== 属性 ====================

    @property
    def working_memory(self) -> WorkingMemoryManager:
        """获取当前会话的工作记忆"""
        if not (current_session := self.session_manager.get_current_session()):
            raise AgentError("No active session")

        if not self._working_memory:
            self._working_memory = self.session_manager.get_working_memory(
                current_session.session_id
            )
        return self._working_memory

    @working_memory.setter
    def working_memory(self, memory: WorkingMemoryManager) -> None:
        """设置当前会话的工作记忆"""
        self._working_memory = memory

    @property
    def background_manager(self) -> BackgroundManager:
        """获取后台管理器（懒加载）"""
        if self._background_manager is None:
            self._background_manager = self._create_background_manager()
        return self._background_manager

    @property
    def is_shutting_down(self) -> bool:
        """是否正在关闭"""
        return self._shutting_down

    # ==================== 初始化 ====================

    def _setup(self) -> None:
        """设置 Agent"""
        self.system_prompt = self._build_system_prompt()
        character_name = safe_get(self.config, "character.name", "unknown")
        logger.info(f"Agent 初始化完成，角色: {character_name}")

    def _build_system_prompt(self) -> str:
        """构建系统提示词"""
        prompt = safe_get(self.config, "character.system_prompt", "")

        # 添加工具说明
        if self.config.tool.enabled and (tools := self.tool_registry.list()):
            tools_desc = "\n\n【可用工具】\n"
            tools_desc += "\n".join(f"- {t.name}: {t.description}" for t in tools)
            prompt += tools_desc
            prompt += "\n当需要获取外部信息时，请调用相应的工具。调用工具后，将结果整合到回复中。"

        return prompt

    def _create_background_manager(self) -> BackgroundManager:
        """创建后台管理器"""
        manager = BackgroundManager(max_workers=2, max_queue_size=50)

        # 注册记忆工作器
        manager.register_memory_worker(
            MemoryWorker(self.semantic_memory, self.config.memory)
        )

        # 注册持久化工作器
        manager.register_persistence_worker(
            PersistenceWorker(self.session_manager._persistence)
        )

        # 注册完成回调
        manager.on_complete(self._on_background_task_complete)

        return manager

    def _setup_signal_handlers(self) -> None:
        """设置信号处理器"""
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(
                    sig, lambda s=sig: asyncio.create_task(self._handle_signal(s))
                )
            logger.debug("信号处理器已设置")
        except NotImplementedError:
            # Windows 不支持 add_signal_handler
            logger.debug("当前平台不支持 add_signal_handler")
            self._setup_windows_signal_handler()

    def _setup_windows_signal_handler(self) -> None:
        """Windows 平台的信号处理"""
        import signal as sig

        def windows_handler(signum, frame):
            if not self._shutting_down:
                self._shutting_down = True
                logger.info("收到中断信号，正在保存数据...")
                self._sync_save()
                logger.info("数据已保存，正在退出...")
                sys.exit(0)

        sig.signal(signal.SIGINT, windows_handler)
        sig.signal(signal.SIGTERM, windows_handler)

    async def _handle_signal(self, signum: int) -> None:
        """异步处理信号"""
        if self._shutting_down:
            return

        self._shutting_down = True
        signal_name = signal.Signals(signum).name

        logger.info(f"收到 {signal_name} 信号，正在优雅关闭...")

        # 取消当前请求
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()

        # 等待当前操作完成（最多 3 秒）
        try:
            await asyncio.wait_for(self._graceful_shutdown(), timeout=3.0)
        except asyncio.TimeoutError:
            logger.warning("优雅关闭超时，强制保存并退出")

        # 同步保存
        self._sync_save()

        logger.info("数据已保存，正在退出...")
        self._shutdown_event.set()
        sys.exit(0)

    async def _graceful_shutdown(self) -> None:
        """优雅关闭"""
        # 取消后台任务
        if self._bg_task and not self._bg_task.done():
            self._bg_task.cancel()
            try:
                await self._bg_task
            except asyncio.CancelledError:
                pass

        # 停止后台管理器
        if self._background_manager:
            await self._background_manager.stop(wait=True)

    def _sync_save(self) -> None:
        """同步保存（确保数据写入磁盘）"""
        try:
            if self.config.session.auto_save:
                current = self.session_manager.get_current_session()
                if current:  # 添加检查
                    self.session_manager.save_working_memory()
                    self.session_manager.save_current()
                    logger.info(
                        f"已保存会话数据 (轮数: {len(self.working_memory) // 2})"
                    )
        except Exception as e:
            logger.error(f"保存数据时出错: {e}")

    async def _start_background_manager(self) -> None:
        """启动后台管理器"""
        if self._bg_task is None and not self._shutting_down:
            self._bg_task = asyncio.create_task(self.background_manager.start())
            logger.debug("后台管理器已启动")

    async def _on_background_task_complete(self, result: TaskResult) -> None:
        """后台任务完成回调"""
        if not result.success:
            logger.warning(f"后台任务失败 [{result.task_id}]: {result.error}")
            if result.result and result.result.get("operation") == "save_messages":
                self._save_pending = False

        # 如果是持久化任务完成，重置 pending 标记
        if result.result and result.result.get("operation") == "save_messages":
            self._save_pending = False

    # ==================== 消息构建 ====================

    def _build_messages(self, user_input: str) -> list[dict[str, str]]:
        """构建消息列表"""
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self.system_prompt}
        ]

        # 情景记忆（摘要）
        if episodic_context := self.episodic_memory.get_relevant_context(user_input):
            messages.append(
                {
                    "role": "system",
                    "content": "【历史记忆摘要】\n" + "\n".join(episodic_context),
                }
            )

        # 语义记忆（相关记忆）
        if semantic_context := self.semantic_memory.get_relevant_context(user_input):
            messages.append(
                {
                    "role": "system",
                    "content": "【相关记忆】\n" + "\n".join(semantic_context),
                }
            )

        # 工作记忆（当前对话）
        messages.extend(self.working_memory.get_context())

        # 当前用户输入
        messages.append({"role": "user", "content": user_input})

        return messages

    def _build_continuation_messages(self) -> list[dict[str, str]]:
        """构建继续对话的消息列表"""
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self.system_prompt}
        ]
        messages.extend(self.working_memory.get_context())
        messages.append(
            {
                "role": "system",
                "content": "工具调用已完成，请自然地将结果信息融入你的回复中，保持角色风格。",
            }
        )
        return messages

    # ==================== 模型调用 ====================

    async def _call_model(
        self, messages: list[dict[str, str]], tools: list[dict] | None = None
    ) -> ChatResponse:
        """调用模型（异步）- 带超时控制"""
        kwargs: dict = {
            "model": self.config.model.name,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.config.model.temperature,
                "top_p": self.config.model.top_p,
                "num_predict": self.config.model.max_tokens,
            },
        }

        if self.config.model.think:
            kwargs["think"] = True

        if tools:
            kwargs["tools"] = tools
            logger.debug(f"传递了 {len(tools)} 个工具到模型")

        try:
            return await asyncio.wait_for(
                self._ollama_chat_async(**kwargs), timeout=self.config.model.timeout
            )
        except asyncio.TimeoutError:
            raise ModelError(f"模型调用超时 ({self.config.model.timeout}s)")
        except Exception as e:
            raise ModelError(f"模型调用失败: {e}") from e

    async def _call_model_stream(
        self, messages: list[dict[str, str]], tools: list[dict] | None = None
    ) -> AsyncIterator[StreamChunk]:
        """流式调用模型，返回流式迭代器"""
        kwargs: dict = {
            "model": self.config.model.name,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": self.config.model.temperature,
                "top_p": self.config.model.top_p,
                "num_predict": self.config.model.max_tokens,
            },
        }

        if self.config.model.think:
            kwargs["think"] = True

        if tools:
            kwargs["tools"] = tools

        try:
            from concurrent.futures import ThreadPoolExecutor

            def run_stream():
                for chunk in ollama.chat(**kwargs):
                    if self._shutting_down:
                        break
                    yield chunk

            executor = ThreadPoolExecutor(max_workers=1)
            loop = asyncio.get_event_loop()
            queue: asyncio.Queue = asyncio.Queue()

            def producer():
                try:
                    for chunk in run_stream():
                        loop.call_soon_threadsafe(queue.put_nowait, chunk)
                except Exception as e:
                    loop.call_soon_threadsafe(queue.put_nowait, e)
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, None)

            executor.submit(producer)

            while True:
                try:
                    item = await asyncio.wait_for(
                        queue.get(), timeout=self.config.model.timeout
                    )
                except asyncio.TimeoutError:
                    raise ModelError(f"流式模型调用超时 ({self.config.model.timeout}s)")

                if item is None:
                    break
                if isinstance(item, Exception):
                    raise ModelError(f"流式模型调用失败: {item}") from item

                if hasattr(item, "message"):
                    if hasattr(item.message, "tool_calls") and item.message.tool_calls:
                        yield StreamChunk(
                            is_tool_call=True, tool_info={"message": item.message}
                        )
                    elif content := getattr(item.message, "content", ""):
                        yield StreamChunk(content=content)
                elif isinstance(item, dict):
                    if message := item.get("message", {}):
                        if message.get("tool_calls"):
                            yield StreamChunk(
                                is_tool_call=True, tool_info={"message": message}
                            )
                        elif content := message.get("content"):
                            yield StreamChunk(content=content)

            executor.shutdown(wait=False)

        except Exception as e:
            raise ModelError(f"流式模型调用失败: {e}") from e

    # ==================== 工具处理 ====================

    async def _handle_tool_calls(self, response: ChatResponse) -> list[dict] | None:
        """处理工具调用"""
        message = getattr(response, "message", None) or response.get("message", {})
        tool_calls = getattr(message, "tool_calls", []) or message.get("tool_calls", [])

        if not tool_calls:
            return None

        logger.info(f"检测到 {len(tool_calls)} 个工具调用")

        if parsed_calls := self.tool_executor.parse_tool_calls(message):
            return await self.tool_executor.execute_batch(parsed_calls)

        return None

    async def _handle_tool_calls_from_message(
        self, message: Message
    ) -> list[dict] | None:
        """处理来自流式响应的 Message 对象的工具调用"""
        if not (tool_calls := getattr(message, "tool_calls", [])):
            return None

        logger.info(f"检测到 {len(tool_calls)} 个工具调用")
        for tc in tool_calls:
            if hasattr(tc, "function"):
                logger.info(f"工具调用: {tc.function.name}")

        if parsed_calls := self.tool_executor.parse_tool_calls_from_message(message):
            return await self.tool_executor.execute_batch(parsed_calls)

        return None

    async def _handle_tool_chain(
        self, partial_content: str, tool_results: list[dict]
    ) -> str:
        """处理工具调用链，返回完整响应"""
        self._record_tool_results(tool_results)

        if partial_content:
            self.working_memory.add_message("assistant", partial_content)

        continuation = await self._continue_with_tool_results()
        return partial_content + continuation

    async def _continue_with_tool_results(self) -> str:
        """带着工具结果继续对话"""
        messages = self._build_continuation_messages()
        response = await self._call_model(messages, None)
        return response.get("message", {}).get("content", "")

    async def _continue_with_tool_results_stream(self) -> AsyncIterator[StreamChunk]:
        """带着工具结果继续对话 - 流式版本"""
        messages = self._build_continuation_messages()
        async for chunk in self._call_model_stream(messages, None):
            yield chunk

    # ==================== 记录与保存 ====================

    def _record_user_message(self, content: str) -> None:
        """记录用户消息"""
        character_name = safe_get(self.config, "character.name", "default")

        self.working_memory.add_message("user", content)
        self.episodic_memory.add_message(
            MemoryRecord(
                content=content,
                role="user",
                character_id=character_name,
            )
        )

    def _record_assistant_message(self, content: str) -> None:
        """记录助手消息（带去重保护）"""
        if not content:
            return

        wm = self.working_memory
        character_name = safe_get(self.config, "character.name", "default")

        if wm._memory.messages:
            if (last_msg := wm._memory.messages[-1])[
                "role"
            ] == "assistant" and last_msg["content"] == content:
                logger.debug("跳过重复的助手消息记录")
                return

        self.working_memory.add_message("assistant", content)
        self.episodic_memory.add_message(
            MemoryRecord(
                content=content,
                role="assistant",
                character_id=character_name,
            )
        )

    def _record_tool_results(self, results: list[dict]) -> None:
        """记录工具调用结果"""
        character_name = safe_get(self.config, "character.name", "default")

        for result in results:
            self.working_memory.add_message(result["role"], result["content"])
            self.episodic_memory.add_message(
                MemoryRecord(
                    content=result["content"],
                    role="tool",
                    character_id=character_name,
                    metadata={"tool_name": result.get("name", "")},
                )
            )

    # ==================== 保存逻辑（去重优化） ====================

    def _should_save(self) -> bool:
        """判断是否应该保存（去重）"""
        if self._shutting_down:
            return True  # 关闭时强制保存

        current_turn = len(self.working_memory) // 2

        # 如果没有新消息，不保存
        if current_turn <= self._last_saved_turn:
            return False

        # 如果已有保存任务在队列中，不重复提交
        if self._save_pending:
            logger.debug("保存任务已在队列中，跳过")
            return False

        return True

    def _mark_save_pending(self) -> None:
        """标记保存任务为 pending"""
        self._save_pending = True
        self._last_saved_turn = len(self.working_memory) // 2

    async def _save_async_if_needed(self) -> None:
        """异步保存（提交到后台管理器）"""
        if not self.config.session.auto_save:
            return

        if not self._should_save():
            return

        self._mark_save_pending()

        current_session = self.session_manager.get_current_session()
        if current_session is None:
            return

        messages = self.working_memory.get_context()

        # 提交到后台管理器
        await self._start_background_manager()
        self.background_manager.submit_persistence_task(
            operation="save_messages",
            data={
                "session_id": current_session.session_id,
                "messages": messages,
            },
            priority=TaskPriority.LOW,
            timeout=10.0,
        )

        logger.debug(f"已提交异步保存任务 (轮数: {len(messages) // 2})")

    # ==================== 自动记忆 ====================

    def _should_auto_memory(self, user_input: str, assistant_response: str) -> bool:
        """判断是否需要自动记忆"""
        if not self.config.memory.auto_memory_enabled:
            return False

        # 关闭时不提交新任务
        if self._shutting_down:
            return False

        # 快速预判，避免无意义的任务提交
        if len(user_input) < 20 and len(assistant_response) < 50:
            return False

        return True

    async def _auto_memory_async(
        self, user_input: str, assistant_response: str
    ) -> None:
        """异步自动记忆（提交到后台）"""
        if not self._should_auto_memory(user_input, assistant_response):
            return

        await self._start_background_manager()
        self.background_manager.submit_memory_task(
            user_input=user_input,
            assistant_response=assistant_response,
            priority=TaskPriority.LOW,
            timeout=5.0,
        )

    # ==================== 核心 API ====================

    async def send(self, user_input: str) -> str:
        """发送消息并获取完整回复（非流式）"""
        if self._shutting_down:
            return ""

        # 使用信号量限制并发
        async with self._request_semaphore:
            request_id = get_request_id()
            logger.debug(f"[{request_id}] 开始处理请求")

            try:
                self._current_task = asyncio.current_task()
                return await self._do_send(user_input)
            except asyncio.CancelledError:
                logger.info(f"[{request_id}] 请求被取消")
                raise
            finally:
                self._current_task = None
                logger.debug(f"[{request_id}] 请求处理完成")

    async def _do_send(self, user_input: str) -> str:
        """实际执行发送逻辑"""
        self._record_user_message(user_input)

        tools = self.tool_registry.get_schemas() if self.config.tool.enabled else None
        messages = self._build_messages(user_input)
        response = await self._call_model(messages, tools)
        content = response.get("message", {}).get("content", "")

        if tool_results := await self._handle_tool_calls(response):
            content = await self._handle_tool_chain(content, tool_results)

        if content:
            self._record_assistant_message(content)
            await self._auto_memory_async(user_input, content)

        await self._save_async_if_needed()
        return content

    async def send_stream(self, user_input: str) -> AsyncIterator[StreamChunk]:
        """发送消息并获取流式回复迭代器"""
        if self._shutting_down:
            return

        async with self._request_semaphore:
            request_id = get_request_id()
            logger.debug(f"[{request_id}] 开始处理流式请求")

            try:
                self._current_task = asyncio.current_task()
                async for chunk in self._do_send_stream(user_input):
                    yield chunk
            except asyncio.CancelledError:
                logger.info(f"[{request_id}] 流式请求被取消")
                raise
            finally:
                self._current_task = None
                logger.debug(f"[{request_id}] 流式请求处理完成")

    async def _do_send_stream(self, user_input: str) -> AsyncIterator[StreamChunk]:
        """实际执行流式发送逻辑"""
        self._record_user_message(user_input)

        tools = self.tool_registry.get_schemas() if self.config.tool.enabled else None
        messages = self._build_messages(user_input)

        full_content = ""
        tool_calls_message = None

        async for chunk in self._call_model_stream(messages, tools):
            if self._shutting_down:
                break
            if chunk.is_tool_call and chunk.tool_info:
                tool_calls_message = chunk.tool_info["message"]
            else:
                full_content += chunk.content
            yield chunk

        if self._shutting_down:
            return

        if tool_calls_message and (
            tool_results := await self._handle_tool_calls_from_message(
                tool_calls_message
            )
        ):
            self._record_tool_results(tool_results)

            async for chunk in self._continue_with_tool_results_stream():
                if self._shutting_down:
                    break
                full_content += chunk.content
                yield chunk

        if full_content and not self._shutting_down:
            self._record_assistant_message(full_content)
            await self._auto_memory_async(user_input, full_content)

        await self._save_async_if_needed()

    # ==================== 会话管理 ====================

    def rollback(self, turns: int = 1) -> None:
        """回滚对话"""
        wm = self.working_memory
        for _ in range(turns * 2):
            if wm._memory.messages:
                wm._memory.messages.pop()

    def create_session(self) -> SessionContext:
        """创建新会话"""
        # 先保存当前会话
        if self.config.session.auto_save:
            self._sync_save()

        session = self.session_manager.create_session()
        self.working_memory.clear()
        self._last_saved_turn = 0
        self._save_pending = False
        return session

    def resume_session(self, session_id: str) -> bool:
        """恢复会话"""
        # 先保存当前会话
        if self.config.session.auto_save:
            self._sync_save()

        if self.session_manager.set_current_session(session_id):
            self.working_memory = self.session_manager.get_working_memory(session_id)
            self._last_saved_turn = len(self.working_memory) // 2
            self._save_pending = False
            return True
        return False

    def shutdown(self) -> None:
        """关闭 Agent"""
        self._shutting_down = True

        # 停止后台管理器
        if self._bg_task and not self._bg_task.done():
            self._bg_task.cancel()

        # 同步保存最终状态
        self._sync_save()

        logger.info("Agent 已关闭")

    async def wait_for_shutdown(self, timeout: float = 5.0) -> None:
        """等待关闭完成"""
        try:
            await asyncio.wait_for(self._shutdown_event.wait(), timeout)
        except asyncio.TimeoutError:
            pass
