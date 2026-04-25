"""Agent 主类 - 事件驱动版"""

from typing import AsyncIterator, Optional, Literal
from pathlib import Path
import asyncio
from contextvars import ContextVar

from .types import UnifiedMessage, StreamChunk
from .model_client import ModelClient
from .save_coordinator import SaveCoordinator
from .message_builder import MessageBuilder
from .response_handler import ResponseHandler
from .lifecycle import LifecycleManager
from .think_engine import ThinkEngine
from .action_planner import ActionPlanner
from .action_executor import ActionExecutor

from ..config import AppConfig, ConfigLoader
from ..events import EventBus, Event, SystemEvent
from ..event_listeners import (
    CoreListeners,
    MetricsListeners,
    ErrorListeners,
    MemoryServiceListeners,
    PersistenceListeners,
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
from ...utils.logger import logger
from ...utils.helpers import safe_get
from ...background import BackgroundManager, PersistenceWorker


request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class Agent:
    """AI 角色扮演 Agent - 事件驱动版"""

    def __init__(
        self,
        config: AppConfig | None = None,
        config_file: Path | None = None,
        character_file: Path | None = None,
    ) -> None:
        self._init_config(config, config_file, character_file)
        self._init_infrastructure()
        self._init_core_components()
        self._init_memory_system()
        self._init_tool_system()
        self._init_session_system()
        self._init_message_components()
        self._init_event_listeners()
        self._inject_dependencies()
        self._init_lifecycle()
        self._init_think_engine()
        self._init_action_components()
        self._publish_started_event()

        logger.info(f"Agent 初始化完成，角色: {self.config.character.name}")  # type: ignore

    # ==================== 初始化子方法 ====================

    def _init_config(self, config, config_file, character_file) -> None:
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
        self.event_bus = EventBus(enable_trace=True)
        self._request_semaphore = asyncio.Semaphore(1)
        self._working_memory: Optional[WorkingMemoryManager] = None

    def _init_core_components(self) -> None:
        self.character_name = safe_get(self.config, "character.name", "default")

    def _init_memory_system(self) -> None:
        self._memory_base_path = self.config.session.save_path
        self._model_client = ModelClient(
            self.config.model,
            event_bus=self.event_bus,
            embedding_config=self.config.embedding,
        )
        self.episodic_memory = EpisodicMemoryManager(
            self.config.memory, self.character_name, None, self._model_client
        )
        self._semantic_memory: Optional[SemanticMemoryManager] = None

    def _init_tool_system(self) -> None:
        self.tool_registry = ToolRegistry()
        self.tool_executor = ToolExecutor(self.tool_registry, event_bus=self.event_bus)

    def _init_session_system(self) -> None:
        self.session_manager = SessionManager(
            self.config.session,
            self.character_name,
            working_max_turns=self.config.memory.working_max_turns,
        )

    def _init_message_components(self) -> None:
        self._message_builder: Optional[MessageBuilder] = None
        self._save_coordinator: Optional[SaveCoordinator] = None
        self._response_handler: Optional[ResponseHandler] = None
        self._background_manager: Optional[BackgroundManager] = None

    def _init_event_listeners(self) -> None:
        self.core_listeners = CoreListeners(self, self.event_bus)
        self.memory_service_listeners = MemoryServiceListeners(self, self.event_bus)
        self.metrics_listeners = MetricsListeners(self.event_bus)
        self.error_listeners = ErrorListeners(self.event_bus)
        self.persistence_listeners = PersistenceListeners(self, self.event_bus)
        logger.debug("所有事件监听器已注册")

    def _inject_dependencies(self) -> None:
        set_event_bus(self.event_bus)

    def _init_lifecycle(self) -> None:
        self.lifecycle = LifecycleManager(on_shutdown=self._on_shutdown)
        self.lifecycle.setup_signal_handlers()

    def _init_think_engine(self) -> None:
        self._think_engine: Optional[ThinkEngine] = None

    def _init_action_components(self) -> None:
        self._action_planner: Optional[ActionPlanner] = None
        self._action_executor: Optional[ActionExecutor] = None

    def _publish_started_event(self) -> None:
        self.event_bus.publish(
            Event(
                type=SystemEvent.AGENT_STARTED,
                source="agent",
                data={"character": self.config.character.name},  # type: ignore
            )
        )

    def _build_system_prompt(self) -> str:
        if not self.config.character:
            raise AgentError("No Character be roleplayed.")
        return self.config.character.system_prompt

    # ==================== 懒加载属性 ====================

    @property
    def semantic_memory(self) -> SemanticMemoryManager:
        if self._semantic_memory is None:
            current_session = self.session_manager.get_current_session()
            if not current_session:
                raise AgentError("No active session for semantic memory")

            memory_path = (
                self._memory_base_path / self.character_name / "memory" / current_session.session_id
            )
            memory_path.mkdir(parents=True, exist_ok=True)

            self._semantic_memory = SemanticMemoryManager(
                self.config.memory, self.character_name, memory_path, self._model_client
            )
            logger.debug(f"语义记忆已初始化: {memory_path}")
        return self._semantic_memory

    @property
    def working_memory(self) -> WorkingMemoryManager:
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
        if self._response_handler is None:
            self._response_handler = ResponseHandler(
                config=self.config,
                working_memory=self.working_memory,
                tool_executor=self.tool_executor,
                model_client=self._model_client,
                message_builder=self.message_builder,
            )
        return self._response_handler

    @property
    def is_shutting_down(self) -> bool:
        return self.lifecycle.is_shutting_down

    # ==================== 核心 API ====================

    async def send(
        self, user_input: str, system_contexts: list[str] | None = None
    ) -> UnifiedMessage | None:
        """发送消息（非流式）- 完全事件驱动"""
        if self.is_shutting_down:
            return None

        # 准备接收响应
        response_future = self._action_executor.prepare_response()  # type: ignore

        # 发布消息接收事件
        self.event_bus.publish(
            Event(
                type=SystemEvent.MESSAGE_RECEIVED,
                source="agent",
                data={"content": user_input, "system_contexts": system_contexts},
            )
        )

        try:
            full_response = await asyncio.wait_for(response_future, timeout=60.0)
            if full_response:
                return UnifiedMessage(role="assistant", content=full_response)
        except asyncio.TimeoutError:
            logger.warning("等待响应超时")
            return UnifiedMessage(role="assistant", content="「唔…我有点走神了…」")

        return None

    async def send_stream(
        self, user_input: str, system_contexts: list[str] | None = None
    ) -> AsyncIterator[StreamChunk]:
        """发送消息（流式）- 完全事件驱动"""
        if self.is_shutting_down:
            return

        # 准备接收响应
        response_future = self._action_executor.prepare_response()  # type: ignore

        # 发布消息接收事件
        self.event_bus.publish(
            Event(
                type=SystemEvent.MESSAGE_RECEIVED,
                source="agent",
                data={"content": user_input, "system_contexts": system_contexts},
            )
        )

        # 流式返回
        full_response = ""
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(self._action_executor.get_chunk(), timeout=0.1)  # type: ignore
                    if chunk:
                        full_response += chunk
                        yield StreamChunk(content=chunk)
                except asyncio.TimeoutError:
                    if response_future.done():
                        break
                    continue
        finally:
            self._action_executor.complete_response(full_response)  # type: ignore

    # ==================== 会话管理 ====================

    def create_session(self) -> SessionContext:
        session = self.session_manager.create_session()
        self._working_memory = None
        self._semantic_memory = None
        self.event_bus.publish(
            Event(type=SystemEvent.SESSION_CREATED, source="agent", data={"session": session})
        )
        return session

    def resume_session(self, session_id: str) -> bool:
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
        await self.save_coordinator.save_async(self.working_memory, force=True)

    def rollback(self, num: int = 1, mode: Literal["turns", "messages"] = "turns") -> None:
        wm = self.working_memory
        roll_num = num * 2 if mode == "turns" else num
        for _ in range(roll_num):
            if wm._memory.messages:
                wm._memory.messages.pop()

    # ==================== 生命周期 ====================

    async def start(self) -> None:
        await self.event_bus.start()
        await self._ensure_background_manager()
        await self.episodic_memory.initialize()

        # 启动思考引擎
        if self._think_engine is None and self.semantic_memory is not None:
            self._think_engine = ThinkEngine(
                semantic_memory=self.semantic_memory,
                model_client=self._model_client,
                event_bus=self.event_bus,
                character_name=self.character_name,
                config=self.config.think_engine,
            )
        if self._think_engine:
            await self._think_engine.start()

        # 初始化决策组件
        if self._action_planner is None:
            self._action_planner = ActionPlanner(
                character_name=self.character_name,
                model_client=self._model_client,
                working_memory=self.working_memory,
                semantic_memory=self.semantic_memory,
                event_bus=self.event_bus,
            )
        if self._action_executor is None:
            self._action_executor = ActionExecutor(self, self.event_bus)

        # 订阅 GENERATE_RESPONSE 事件
        self.event_bus.subscribe(
            SystemEvent.GENERATE_RESPONSE,
            self._on_generate_response,
        )

        logger.info("Agent 已启动")

    async def _on_generate_response(self, event: Event) -> None:
        user_input = event.data.get("user_input", "")
        system_contexts = event.data.get("system_contexts", [])

        full_response = ""
        try:
            await self._ensure_background_manager()
            messages = self.message_builder.build(user_input, system_contexts)
            tools = self.tool_registry.get_schemas() if self.config.tool.enabled else None

            async for chunk in self.response_handler.process_stream(messages, tools):
                if self.is_shutting_down:
                    break
                if chunk.content:
                    full_response += chunk.content
                    await self._action_executor.feed_chunk(chunk.content)  # type: ignore

        except Exception as e:
            logger.error(f"生成响应异常: {e}")
            error_msg = f"\n[出了点问题]\n"
            if not full_response:
                full_response = error_msg
                await self._action_executor.feed_chunk(error_msg)  # type: ignore

        finally:
            # 🔑 无论如何都要把控制权还给用户
            if self._action_executor:
                self._action_executor.complete_response(full_response)

            if full_response and "响应中断" not in full_response:
                self.event_bus.publish(
                    Event(
                        type=SystemEvent.MESSAGE_SENT,
                        source="agent",
                        data={"content": full_response},
                    )
                )

    async def _on_shutdown(self) -> None:
        self.event_bus.publish(Event(type=SystemEvent.AGENT_SHUTDOWN, source="agent"))

        if self._think_engine:
            await self._think_engine.stop()

        if self._background_manager:
            await self._background_manager.stop(wait=True)

        try:
            await self.save_coordinator.save_async(self.working_memory, force=True)
        except Exception as e:
            logger.error(f"关闭时保存数据出错: {e}")

        await self.event_bus.stop()
        logger.info("Agent 已关闭")

    async def shutdown(self) -> None:
        await self.lifecycle.shutdown()

    # ==================== 私有辅助方法 ====================

    async def _ensure_background_manager(self) -> None:
        if self._background_manager is None:
            self._background_manager = self._create_background_manager()
            await self._background_manager.start()
            if self._save_coordinator:
                self._save_coordinator.set_background_manager(self._background_manager)

    def _create_background_manager(self) -> BackgroundManager:
        manager = BackgroundManager(max_workers=2, max_queue_size=50)
        manager.register_persistence_worker(PersistenceWorker(self.session_manager._persistence))
        return manager

    @property
    def metrics(self) -> dict:
        return {
            "event_bus": self.event_bus.stats,
            "app": self.metrics_listeners.metrics if hasattr(self, "metrics_listeners") else {},
        }
