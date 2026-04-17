"""Agent 主类 - 事件驱动版"""

from typing import AsyncIterator, Optional, Literal
from pathlib import Path
import asyncio
from contextvars import ContextVar

from ollama import Message

from .model_client import ModelClient, StreamChunk
from .save_coordinator import SaveCoordinator
from .message_builder import MessageBuilder
from .response_handler import ResponseHandler
from .lifecycle import LifecycleManager

from ..config import AppConfig, ConfigLoader
from ..events import EventBus, Event, SystemEvent
from ..event_listeners import (
    CoreListeners,
    MetricsListeners,
    ErrorListeners,
    MemoryServiceListeners,
)
from ..exceptions import AgentError

from ...memory.working import WorkingMemoryManager
from ...memory.episodic import EpisodicMemoryManager
from ...memory.semantic import SemanticMemoryManager
from ...tools.registry import ToolRegistry
from ...tools.executor import ToolExecutor
from ...tools.tool_builtin.memory_tool import set_event_bus
from ...session.manager import SessionManager
from ...session.context import SessionContext
from ...utils.logging import logger
from ...utils.helpers import safe_get
from ...background import BackgroundManager, PersistenceWorker


request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class Agent:
    """AI 角色扮演 Agent - 事件驱动版"""

    # ==================== 初始化 ====================

    def __init__(
        self,
        config: AppConfig | None = None,
        config_file: Path | None = None,
        character_file: Path | None = None,
    ) -> None:
        """初始化 Agent，所有组件在 __init__ 中完成创建和注册"""

        # ---------- 1. 加载配置 ----------
        self._init_config(config, config_file, character_file)

        # ---------- 2. 初始化基础设施 ----------
        self._init_infrastructure()

        # ---------- 3. 初始化核心组件 ----------
        self._init_core_components()

        # ---------- 4. 初始化记忆系统 ----------
        self._init_memory_system()

        # ---------- 5. 初始化工具系统 ----------
        self._init_tool_system()

        # ---------- 6. 初始化会话管理 ----------
        self._init_session_system()

        # ---------- 7. 初始化消息处理组件 ----------
        self._init_message_components()

        # ---------- 8. 注册事件监听器 ----------
        self._init_event_listeners()

        # ---------- 9. 注入依赖 ----------
        self._inject_dependencies()

        # ---------- 10. 初始化生命周期管理器 ----------
        self._init_lifecycle()

        # ---------- 11. 发布启动事件 ----------
        self._publish_started_event()

        logger.info(f"Agent 初始化完成，角色: {self.config.character.name}")  # type: ignore

    # ==================== 初始化子方法 ====================

    def _init_config(
        self,
        config: AppConfig | None,
        config_file: Path | None,
        character_file: Path | None,
    ) -> None:
        """加载配置"""
        loader = ConfigLoader()
        self.config = config or loader.load(config_file)

        if character_file:
            self.config.character = loader.load_character(character_file)
        elif self.config.character_file:
            self.config.character = loader.load_character(self.config.character_file)

        if not self.config.character:
            raise AgentError("No character loaded")

        self.system_prompt = self._build_system_prompt()

    def _init_infrastructure(self) -> None:
        """初始化基础设施"""
        self.event_bus = EventBus(enable_trace=True)
        self._request_semaphore = asyncio.Semaphore(1)
        self._working_memory: Optional[WorkingMemoryManager] = None

    def _init_core_components(self) -> None:
        """初始化核心组件"""
        character_name = safe_get(self.config, "character.name", "default")
        self.character_name = character_name

    def _init_memory_system(self) -> None:
        """初始化记忆系统"""
        character_name = self.character_name
        self._memory_base_path = self.config.session.save_path

        # 模型客户端（记忆系统也需要）
        self._ollama_client = ModelClient(self.config.model, event_bus=self.event_bus)

        # 情景记忆（不依赖路径）
        self.episodic_memory = EpisodicMemoryManager(
            self.config.memory, character_name, None, self._ollama_client
        )

        self._semantic_memory: Optional[SemanticMemoryManager] = None

    def _init_tool_system(self) -> None:
        """初始化工具系统"""
        self.tool_registry = ToolRegistry()
        # 🆕 创建 ToolExecutor 时传入 event_bus
        self.tool_executor = ToolExecutor(self.tool_registry, event_bus=self.event_bus)

    def _init_session_system(self) -> None:
        """初始化会话管理"""
        self.session_manager = SessionManager(
            self.config.session,
            self.character_name,
            working_max_turns=self.config.memory.working_max_turns,
        )

    def _init_message_components(self) -> None:
        """初始化消息处理组件（懒加载占位）"""
        self._message_builder: Optional[MessageBuilder] = None
        self._save_coordinator: Optional[SaveCoordinator] = None
        self._response_handler: Optional[ResponseHandler] = None
        self._background_manager: Optional[BackgroundManager] = None

    def _init_event_listeners(self) -> None:
        """注册所有事件监听器"""
        self.core_listeners = CoreListeners(self, self.event_bus)
        self.memory_service_listeners = MemoryServiceListeners(self, self.event_bus)
        self.metrics_listeners = MetricsListeners(self.event_bus)
        self.error_listeners = ErrorListeners(self.event_bus)

        logger.debug("所有事件监听器已注册")

    def _inject_dependencies(self) -> None:
        """注入依赖到各模块"""
        # 注入事件总线到工具模块
        set_event_bus(self.event_bus)

    def _init_lifecycle(self) -> None:
        """初始化生命周期管理器"""
        self.lifecycle = LifecycleManager(on_shutdown=self._on_shutdown)
        self.lifecycle.setup_signal_handlers()

    def _publish_started_event(self) -> None:
        """发布 Agent 启动事件"""
        self.event_bus.publish(
            Event(
                type=SystemEvent.AGENT_STARTED,
                source="agent",
                data={"character": self.config.character.name},  # type: ignore
            )
        )

    def _build_system_prompt(self) -> str:
        """构建系统提示词"""
        if not self.config.character:
            raise AgentError("No Character be roleplayed.")
        return self.config.character.system_prompt

    # ==================== 属性（懒加载） ====================

    @property
    def semantic_memory(self) -> SemanticMemoryManager:
        """获取语义记忆（懒加载，依赖当前会话）"""
        if self._semantic_memory is None:
            current_session = self.session_manager.get_current_session()
            if not current_session:
                raise AgentError("No active session for semantic memory")

            session_id = current_session.session_id
            memory_path = self._memory_base_path / self.character_name / "memory" / session_id
            memory_path.mkdir(parents=True, exist_ok=True)

            self._semantic_memory = SemanticMemoryManager(
                self.config.memory, self.character_name, memory_path, self._ollama_client
            )
            logger.debug(f"语义记忆已初始化: {memory_path}")

        return self._semantic_memory

    @property
    def working_memory(self) -> WorkingMemoryManager:
        """获取当前会话的工作记忆"""
        current_session = self.session_manager.get_current_session()
        if not current_session:
            raise AgentError("No active session")
        if not self._working_memory:
            self._working_memory = self.session_manager.get_working_memory(
                current_session.session_id
            )
        return self._working_memory

    @property
    def message_builder(self) -> MessageBuilder:
        """获取消息构建器（懒加载）"""
        if self._message_builder is None:
            self._message_builder = MessageBuilder(
                system_prompt=self.system_prompt,
                working_memory=self.working_memory,
                episodic_memory=self.episodic_memory,
                semantic_memory=self.semantic_memory,
                tool_registry=self.tool_registry,
                tool_enabled=self.config.tool.enabled,
            )
        return self._message_builder

    @property
    def save_coordinator(self) -> SaveCoordinator:
        """获取保存协调器（懒加载）"""
        if self._save_coordinator is None:
            self._save_coordinator = SaveCoordinator(
                session_manager=self.session_manager,
                session_config=self.config.session,
            )
            if self._background_manager:
                self._save_coordinator.set_background_manager(self._background_manager)
        return self._save_coordinator

    @property
    def response_handler(self) -> ResponseHandler:
        """获取响应处理器（懒加载）"""
        if self._response_handler is None:
            self._response_handler = ResponseHandler(
                config=self.config,
                working_memory=self.working_memory,
                episodic_memory=self.episodic_memory,
                tool_executor=self.tool_executor,
                model_client=self._ollama_client,
                message_builder=self.message_builder,
                save_coordinator=self.save_coordinator,
            )
            if self._background_manager:
                self._response_handler.set_background_manager(self._background_manager)
        return self._response_handler

    @property
    def is_shutting_down(self) -> bool:
        """是否正在关闭"""
        return self.lifecycle.is_shutting_down

    # ==================== 核心 API ====================

    async def send(self, user_input: str) -> Message | None:
        """发送消息（非流式）"""
        if self.is_shutting_down:
            return None

        self.event_bus.publish(
            Event(type=SystemEvent.MESSAGE_RECEIVED, source="agent", data={"content": user_input})
        )

        async with self._request_semaphore:
            try:
                self.event_bus.publish(
                    Event(
                        type=SystemEvent.MESSAGE_PROCESSING,
                        source="agent",
                        data={"content": user_input[:50]},
                    )
                )

                response = await self._do_send(user_input)

                if response and response.content:
                    self.event_bus.publish(
                        Event(
                            type=SystemEvent.MESSAGE_SENT,
                            source="agent",
                            data={"content": response.content},
                        )
                    )

                return response

            except Exception as e:
                self.event_bus.publish(
                    Event(
                        type=SystemEvent.ERROR_OCCURRED,
                        source="agent",
                        data={"error": str(e), "context": "send"},
                    )
                )
                raise

    async def _do_send(self, user_input: str) -> Message:
        """实际执行发送逻辑"""
        await self._ensure_background_manager()

        messages = self.message_builder.build(user_input)
        tools = self.tool_registry.get_schemas() if self.config.tool.enabled else None

        return await self.response_handler.process_non_stream(user_input, messages, tools)

    async def send_stream(self, user_input: str) -> AsyncIterator[StreamChunk]:
        """发送消息（流式）"""
        if self.is_shutting_down:
            return

        self.event_bus.publish(
            Event(type=SystemEvent.MESSAGE_RECEIVED, source="agent", data={"content": user_input})
        )

        async with self._request_semaphore:
            full_response = ""
            try:
                async for chunk in self._do_send_stream(user_input):
                    if chunk.content:
                        full_response += chunk.content
                    yield chunk

            finally:
                if full_response:
                    self.event_bus.publish(
                        Event(
                            type=SystemEvent.MESSAGE_SENT,
                            source="agent",
                            data={"content": full_response},
                        )
                    )

    async def _do_send_stream(self, user_input: str) -> AsyncIterator[StreamChunk]:
        """实际执行流式发送逻辑"""
        await self._ensure_background_manager()

        messages = self.message_builder.build(user_input)
        tools = self.tool_registry.get_schemas() if self.config.tool.enabled else None

        async for chunk in self.response_handler.process_stream(user_input, messages, tools):
            if self.is_shutting_down:
                break
            yield chunk

    # ==================== 会话管理 ====================

    def create_session(self) -> SessionContext:
        """创建新会话"""
        session = self.session_manager.create_session()
        self._working_memory = None
        self._semantic_memory = None

        self.event_bus.publish(
            Event(type=SystemEvent.SESSION_CREATED, source="agent", data={"session": session})
        )

        return session

    def resume_session(self, session_id: str) -> bool:
        """恢复会话"""
        if self.session_manager.set_current_session(session_id):
            self._working_memory = None
            self._semantic_memory = None
            session = self.session_manager.get_current_session()

            self.event_bus.publish(
                Event(type=SystemEvent.SESSION_RESUMED, source="agent", data={"session": session})
            )

            return True
        return False

    async def async_save(self) -> None:
        """异步保存会话（强制）"""
        await self.save_coordinator.save_async(self.working_memory, force=True)

    def rollback(self, num: int = 1, mode: Literal["turns", "messages"] = "turns") -> None:
        """回滚对话"""
        wm = self.working_memory
        roll_num = num * 2 if mode == "turns" else num
        for _ in range(roll_num):
            if wm._memory.messages:
                wm._memory.messages.pop()

    # ==================== 生命周期 ====================

    async def start(self) -> None:
        """启动 Agent"""
        await self.event_bus.start()
        await self._ensure_background_manager()
        logger.info("Agent 已启动")

    async def _on_shutdown(self) -> None:
        """关闭回调"""
        self.event_bus.publish(Event(type=SystemEvent.AGENT_SHUTDOWN, source="agent"))

        # 🐛 修复: 使用 force=True 强制保存所有数据，包括异步保存未完成的消息
        # 使用 self.save_coordinator 属性确保懒加载初始化，添加异常保护
        try:
            self.save_coordinator.sync_save(self.working_memory, force=True)
        except Exception as e:
            logger.error(f"关闭时保存数据出错: {e}")

        await self.event_bus.stop()
        logger.info("Agent 已关闭")

    async def shutdown(self) -> None:
        """主动关闭"""
        await self.lifecycle.shutdown()

    # ==================== 私有辅助方法 ====================

    async def _ensure_background_manager(self) -> None:
        """确保后台管理器已启动"""
        if self._background_manager is None:
            self._background_manager = self._create_background_manager()
            await self._background_manager.start()

            if self._save_coordinator:
                self._save_coordinator.set_background_manager(self._background_manager)
            if self._response_handler:
                self._response_handler.set_background_manager(self._background_manager)

    def _create_background_manager(self) -> BackgroundManager:
        """创建后台管理器"""
        manager = BackgroundManager(max_workers=2, max_queue_size=50)
        manager.register_persistence_worker(PersistenceWorker(self.session_manager._persistence))
        return manager

    # ==================== 查询接口 ====================

    @property
    def metrics(self) -> dict:
        """获取运行指标"""
        return {
            "event_bus": self.event_bus.stats,
            "app": self.metrics_listeners.metrics if hasattr(self, "metrics_listeners") else {},
        }
