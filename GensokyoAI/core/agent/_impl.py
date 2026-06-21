"""Agent 主类 - 事件驱动版"""

import asyncio
import json
from collections.abc import AsyncIterator
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Literal

from ...background import BackgroundManager, PersistenceWorker
from ...memory.semantic import SemanticMemoryManager
from ...memory.working import WorkingMemoryManager
from ...session.context import SessionContext
from ...tools.build_service import ToolBuildContext, ToolBuildResult
from ...tools.tool_builtin.memory_tool import set_event_bus
from ...tools.tool_builtin.web_search import configure_web_search_tool
from ...utils.helpers import safe_get
from ...utils.logger import logger
from ..config import AppConfig, ConfigLoader
from ..event_listeners import (
    CoreListeners,
    ErrorListeners,
    MemoryServiceListeners,
    MetricsListeners,
    PersistenceListeners,
)
from ..events import Event, SystemEvent
from ..exceptions import AgentError
from .action_executor import ActionExecutor
from .action_planner import ActionPlanner
from .composition import AgentComposition
from .initiative_timer import InitiativeTimerManager
from .lifecycle import LifecycleManager
from .message_builder import MessageBuilder
from .response_handler import ResponseHandler
from .runtime_context import AgentLazyComponents
from .save_coordinator import SaveCoordinator
from .think_engine import ThinkEngine
from .types import ProviderCapability, StreamChunk, UnifiedMessage

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
        self.config_file = config_file
        self.config = config or loader.load(config_file)

        if character_file:
            self.config.character = loader.load_character(character_file)
        elif self.config.character_file:
            self.config.character = loader.load_character(self.config.character_file)

        if not self.config.character:
            raise AgentError("No character loaded")

        self.system_prompt = self._build_system_prompt()

    def _init_infrastructure(self) -> None:
        self._request_semaphore = asyncio.Semaphore(1)
        self._working_memory: WorkingMemoryManager | None = None
        self._generate_response_subscription_id: str | None = None
        self._stream_first_chunk_timeout = 30.0
        self._stream_idle_timeout = 30.0
        self._stream_total_timeout = 120.0

    def _init_core_components(self) -> None:
        self.character_name = safe_get(self.config, "character.name", "default")

    def _init_memory_system(self) -> None:
        bootstrap = AgentComposition(self.config, self.character_name).bootstrap()
        self.runtime_context = bootstrap.runtime_context
        self._lazy_components: AgentLazyComponents = bootstrap.lazy_components
        context = self.runtime_context
        self.event_bus = context.event_bus
        self._memory_base_path = context.memory_base_path
        self._model_client = context.model_client
        self.episodic_memory = context.episodic_memory
        self._semantic_memory: SemanticMemoryManager | None = None

    def _init_tool_system(self) -> None:
        self.tool_registry = self.runtime_context.tool_registry
        self.tool_executor = self.runtime_context.tool_executor
        self.tool_build_service = self.runtime_context.tool_build_service
        self.external_tool_manager = self.runtime_context.external_tool_manager
        self.model_registry_service = self.runtime_context.model_registry_service

    def _init_session_system(self) -> None:
        self.session_manager = self.runtime_context.session_manager

    def _init_message_components(self) -> None:
        self._message_builder = self._lazy_components.message_builder
        self._save_coordinator = self._lazy_components.save_coordinator
        self._response_handler = self._lazy_components.response_handler
        self._background_manager: BackgroundManager | None = None
        self._initiative_timer: InitiativeTimerManager | None = None
        self._last_initiative_timer_payload: dict | None = None

    def _init_event_listeners(self) -> None:
        self.core_listeners = CoreListeners(self, self.event_bus)
        self.memory_service_listeners = MemoryServiceListeners(self, self.event_bus)
        self.metrics_listeners = MetricsListeners(self.event_bus)
        self.error_listeners = ErrorListeners(self.event_bus)
        self.persistence_listeners = PersistenceListeners(self, self.event_bus)
        logger.debug("所有事件监听器已注册")

    def _inject_dependencies(self) -> None:
        set_event_bus(self.event_bus)
        configure_web_search_tool(self.config.tool)

    def _init_lifecycle(self) -> None:
        self.lifecycle = self._lazy_components.lifecycle or LifecycleManager(
            on_shutdown=self._on_shutdown
        )
        self._lazy_components.lifecycle = self.lifecycle
        self.lifecycle.setup_signal_handlers()

    def _init_think_engine(self) -> None:
        self._think_engine = self._lazy_components.think_engine

    def _init_action_components(self) -> None:
        self._action_planner = self._lazy_components.action_planner
        self._action_executor = self._lazy_components.action_executor

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
                character_name=self.character_name,
                web_search_config=self.config.tool.web_search,
                model_config=self.config.model,
                # _build_tools() 是异步方法，不能在同步属性初始化中直接调用；
                # 每轮响应生成前会在 _on_generate_response() 中 await 后更新结果。
                tool_build_result=None,
            )
            self._lazy_components.message_builder = self._message_builder
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
            self._lazy_components.save_coordinator = self._save_coordinator
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
            self._lazy_components.response_handler = self._response_handler
        return self._response_handler

    @property
    def is_shutting_down(self) -> bool:
        return self.lifecycle.is_shutting_down

    # ==================== 核心 API ====================

    async def send(
        self, user_input: str, system_contexts: list[str] | None = None
    ) -> UnifiedMessage | None:
        """发送消息（非流式）- 完全事件驱动。"""
        if self.is_shutting_down:
            return None

        async with self._request_semaphore:
            if self.is_shutting_down:
                return None
            await self.discard_initiative_timer(reason="user_message_received", source="user")
            response_future = self._action_executor.prepare_response()  # type: ignore
            self._publish_message_received(user_input, system_contexts)

            try:
                full_response = await asyncio.wait_for(response_future, timeout=60.0)
                if full_response:
                    return UnifiedMessage(role="assistant", content=full_response)
            except TimeoutError:
                logger.warning("等待响应超时")
                self._action_executor.cancel_response("send timeout")  # type: ignore
                return UnifiedMessage(role="assistant", content="「唔…我有点走神了…」")

            return None

    async def send_stream(
        self, user_input: str, system_contexts: list[str] | None = None
    ) -> AsyncIterator[StreamChunk]:
        """发送消息（流式）- 完全事件驱动。"""
        if self.is_shutting_down:
            return

        async with self._request_semaphore:
            if self.is_shutting_down:
                return
            await self.discard_initiative_timer(reason="user_message_received", source="user")
            response_future = self._action_executor.prepare_response()  # type: ignore
            self._publish_message_received(user_input, system_contexts)

            full_response = ""
            loop = asyncio.get_running_loop()
            started_at = loop.time()
            last_chunk_at = started_at
            saw_chunk = False
            try:
                while True:
                    timeout = self._next_stream_wait_timeout(
                        started_at=started_at,
                        last_chunk_at=last_chunk_at,
                        saw_chunk=saw_chunk,
                    )
                    if timeout <= 0:
                        raise TimeoutError("stream response timeout")
                    try:
                        chunk = await asyncio.wait_for(
                            self._action_executor.get_chunk(),  # type: ignore
                            timeout=min(0.1, timeout),
                        )
                        if chunk:
                            saw_chunk = True
                            last_chunk_at = loop.time()
                            full_response += chunk
                            yield StreamChunk(content=chunk)
                    except TimeoutError as error:
                        if response_future.done():
                            break
                        if self._stream_timed_out(started_at, last_chunk_at, saw_chunk):
                            raise TimeoutError("stream response timeout") from error
                        continue
            except asyncio.CancelledError, GeneratorExit:
                self._action_executor.cancel_response("stream cancelled")  # type: ignore
                raise
            except TimeoutError as error:
                logger.warning(f"流式响应超时: {error}")
                self._action_executor.cancel_response(str(error))  # type: ignore
                yield StreamChunk(
                    type="error",
                    content="\n[响应超时]\n",
                    error=str(error),
                    error_code="agent.stream.timeout",
                )
            finally:
                self._action_executor.complete_response(full_response)  # type: ignore

    def _publish_message_received(
        self, user_input: str, system_contexts: list[str] | None = None
    ) -> None:
        self.event_bus.publish(
            Event(
                type=SystemEvent.MESSAGE_RECEIVED,
                source="agent",
                data={"content": user_input, "system_contexts": system_contexts},
            )
        )

    def _next_stream_wait_timeout(
        self,
        *,
        started_at: float,
        last_chunk_at: float,
        saw_chunk: bool,
    ) -> float:
        now = asyncio.get_running_loop().time()
        total_remaining = self._stream_total_timeout - (now - started_at)
        activity_deadline = (
            self._stream_idle_timeout if saw_chunk else self._stream_first_chunk_timeout
        )
        activity_remaining = activity_deadline - (now - last_chunk_at)
        return min(total_remaining, activity_remaining)

    def _stream_timed_out(self, started_at: float, last_chunk_at: float, saw_chunk: bool) -> bool:
        now = asyncio.get_running_loop().time()
        if now - started_at >= self._stream_total_timeout:
            return True
        activity_deadline = (
            self._stream_idle_timeout if saw_chunk else self._stream_first_chunk_timeout
        )
        return now - last_chunk_at >= activity_deadline

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
        if mode == "turns":
            wm.rollback_turns(num)
        else:
            wm.rollback_messages(num)

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
                debug_silent_output=self.config.debug_silent_output,
            )
            self._lazy_components.think_engine = self._think_engine
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
                debug_silent_output=self.config.debug_silent_output,
            )
            self._lazy_components.action_planner = self._action_planner
        if self._action_executor is None:
            self._action_executor = ActionExecutor(self, self.event_bus)
            self._lazy_components.action_executor = self._action_executor

        if self._generate_response_subscription_id is None:
            self._generate_response_subscription_id = self.event_bus.subscribe(
                SystemEvent.GENERATE_RESPONSE,
                self._on_generate_response,
            )

        logger.info("Agent 已启动")

    async def _build_tools(self) -> ToolBuildResult:
        """通过 ModelRegistryService + ToolBuildService 构建本轮工具 schema 与 instructions。"""
        model_info = await self.model_registry_service.get_model_info(self.config.model)
        capabilities = set(model_info.capabilities)
        if not capabilities:
            capabilities = {ProviderCapability.CHAT, ProviderCapability.STREAM}
        external_tool_manager = getattr(self, "external_tool_manager", None)
        external_tools = []
        external_tool_policy = None
        if external_tool_manager is not None:
            external_tools = await external_tool_manager.list_tools(refresh=True)
            external_tool_policy = external_tool_manager.policy
        result = self.tool_build_service.build(
            ToolBuildContext(
                tool_config=self.config.tool,
                model_config=self.config.model,
                model_capabilities=capabilities,
                character_name=self.character_name,
                external_tools=external_tools,
                **(
                    {"external_tool_policy": external_tool_policy}
                    if external_tool_policy is not None
                    else {}
                ),
            )
        )
        self._publish_tool_selected_event(result)
        return result

    def _publish_tool_selected_event(self, result: ToolBuildResult) -> None:
        """发布本轮工具选择结果，供 Runtime/客户端观测工具注入控制面。"""
        self.event_bus.publish(
            Event(
                type=SystemEvent.TOOL_CALL_SELECTED,
                source="tool_build_service",
                data={
                    "enabled_tool_names": list(result.enabled_tool_names),
                    "tool_count": len(result.tools),
                    "model_supports_tools": result.model_supports_tools,
                    "disabled_reasons": dict(result.disabled_reasons),
                    "has_instructions": bool(result.instructions),
                },
            )
        )

    async def _on_generate_response(self, event: Event) -> None:
        user_input = event.data.get("user_input", "")
        system_contexts = event.data.get("system_contexts", [])

        full_response = ""
        try:
            await self._ensure_background_manager()
            tool_build_result = await self._build_tools()
            self.message_builder.update_tool_build_result(tool_build_result)
            messages = self.message_builder.build(user_input, system_contexts)
            tools = tool_build_result.tools or None

            async for chunk in self.response_handler.process_stream(messages, tools):
                if self.is_shutting_down:
                    break
                if chunk.content:
                    full_response += chunk.content
                    await self._action_executor.feed_chunk(chunk.content)  # type: ignore

        except Exception as e:
            logger.error(f"生成响应异常: {e}")
            error_msg = "\n[出了点问题]\n"
            if not full_response:
                full_response = error_msg
                await self._action_executor.feed_chunk(error_msg)  # type: ignore

        finally:
            if full_response and "响应中断" not in full_response:
                data = {"content": full_response}
                # reasoning_content 对 DeepSeek thinking mode 是多轮协议状态，
                # 不是调试展示内容；是否显示仍由 UI/日志层的 debug_silent_output 控制。
                if reasoning := self.response_handler.last_assistant_reasoning:
                    data["reasoning_content"] = reasoning
                self.event_bus.publish(
                    Event(
                        type=SystemEvent.MESSAGE_SENT,
                        source="agent",
                        data=data,
                    )
                )
                self._last_initiative_timer_payload = await self.schedule_initiative_timer(
                    full_response
                )

            # 🔑 无论如何都要把控制权还给用户；放在定时器计划后，确保 Runtime 返回可携带 initiative_timer。
            if self._action_executor:
                self._action_executor.complete_response(full_response)

    def _ensure_initiative_timer(self) -> InitiativeTimerManager:
        if self._initiative_timer is None:
            self._initiative_timer = InitiativeTimerManager(
                config=self.config.initiative_timer,
                model_client=self._model_client,
                event_bus=self.event_bus,
                character_name=self.character_name,
                working_memory=self.working_memory,
                debug_silent_output=self.config.debug_silent_output,
                trigger_handler=self._handle_initiative_timer_trigger,
            )
        return self._initiative_timer

    async def schedule_initiative_timer(self, assistant_response: str) -> dict | None:
        if not self.config.initiative_timer.enabled:
            return None
        return await self._ensure_initiative_timer().schedule_after_response(assistant_response)

    async def _handle_initiative_timer_trigger(
        self, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        """定时器到点后：基于摘要先思考，再生成真正主动消息。"""
        pending_summary = str(payload.get("pending_summary") or "").strip()
        timer_id = str(payload.get("timer_id") or "").strip()
        logger.debug(f"[Agent] 主动定时器 {timer_id} 触发，待表达摘要: {pending_summary[:60]}...")
        if not pending_summary:
            logger.debug("[Agent] 主动定时器触发时摘要为空，跳过生成")
            return None

        await self._ensure_background_manager()
        tool_build_result = await self._build_tools()
        self.message_builder.update_tool_build_result(tool_build_result)

        recent_messages = self.working_memory.get_recent(8)
        recent_context = "\n".join(
            f"{item.get('role', 'unknown')}: {item.get('content', '')}"
            for item in recent_messages
            if isinstance(item.get("content"), str)
        )
        thought_prompt = f"""你是 {self.character_name}。

主动定时器到点了，这表示你已经决定稍后要主动开口。

【待表达意图摘要】
{pending_summary}

【最近对话】
{recent_context or "无"}

请先进行说话前的内部思考：
- 根据当前上下文重新组织这次主动发言的重点。
- 不要判断要不要说；到点即代表要说。
- 不要写最终要发送给用户的完整话术。
- 只输出简短内部思考。"""
        logger.trace(f"[Agent] 主动消息思考 prompt:\n{thought_prompt}")
        thought = ""
        try:
            thought_response = await self._model_client.chat(
                messages=[{"role": "system", "content": thought_prompt}],
                options={
                    "temperature": self.config.think_engine.think_temperature,
                    "num_predict": self.config.think_engine.think_max_tokens,
                    "max_tokens": self.config.think_engine.think_max_tokens,
                },
            )
            content = thought_response.message.content
            thought = content.strip() if isinstance(content, str) else ""
            logger.debug(f"[Agent] 主动消息思考结果: {thought[:100]}...")
        except Exception as error:
            logger.error(f"主动定时器说话前思考失败: {error}")

        system_contexts = [
            "【主动定时器触发 · 无新用户输入】\n"
            "用户没有发送任何新消息。这是你自己在之前的回复中决定要说的话，现在到了该开口的时刻。\n"
            "你的任务是：衔接你刚才的最后一句话，自然地把话题延续下去，而不是回应一个新的问题。\n"
            "不要重复你刚才已经说过的内容；不要反问用户“为什么又问一遍”或表现出被重复打扰；"
            "不要解释定时器、摘要或内部思考；直接以你的角色口吻自然开口。\n"
            f"待表达意图摘要：{pending_summary}\n"
            f"说话前内部思考：{thought or '无'}"
        ]
        messages = self.message_builder.build("", system_contexts)
        # 工作记忆末尾是助手自己的上一条回复，必须补一条 user 消息让模型继续生成下一句
        messages.append(
            {
                "role": "user",
                "content": "（没有新用户输入，这是你自己决定要说的话，请按照上面的摘要和内部思考自然地主动开口。）",
            }
        )
        max_tokens = self.config.think_engine.initiative_max_tokens
        initiative_options: dict[str, Any] = {
            "temperature": self.config.think_engine.initiative_temperature,
        }
        if max_tokens > 0:
            initiative_options["num_predict"] = max_tokens
            initiative_options["max_tokens"] = max_tokens
        use_stream = self.config.model.stream

        logger.trace(
            f"[Agent] 主动消息生成请求 messages:\n"
            f"{json.dumps(messages, ensure_ascii=False, indent=2)}"
        )

        message = ""
        try:
            if use_stream:
                chunks: list[str] = []
                async for chunk in self._model_client.chat_stream(
                    messages=messages,
                    options=initiative_options,
                ):
                    if self.is_shutting_down:
                        break
                    chunk_text = chunk.content if hasattr(chunk, "content") else ""
                    if chunk_text:
                        chunks.append(chunk_text)
                        logger.trace(f"[Agent] 主动消息流式 chunk: {chunk_text!r}")
                        self.event_bus.publish(
                            Event(
                                type=SystemEvent.THINK_ENGINE_INITIATIVE_CHUNK,
                                source="initiative_timer",
                                data={"content": chunk_text, "done": False},
                            )
                        )
                message = "".join(chunks).strip()
                logger.debug(f"[Agent] 主动消息流式生成完成，长度: {len(message)}")
                # 发送流式结束标记
                self.event_bus.publish(
                    Event(
                        type=SystemEvent.THINK_ENGINE_INITIATIVE_CHUNK,
                        source="initiative_timer",
                        data={"content": "", "done": True},
                    )
                )
            else:
                response = await self._model_client.chat(
                    messages=messages,
                    options=initiative_options,
                )
                content = response.message.content
                message = content.strip() if isinstance(content, str) else ""
                logger.debug(f"[Agent] 主动消息非流式生成完成，长度: {len(message)}")
        except Exception as error:
            logger.error(f"主动定时器主动消息生成失败: {error}")
            message = ""

        if not message:
            return {
                "sent": False,
                "timer_id": timer_id,
                "pending_summary": pending_summary,
                "thought": thought,
            }

        # 发布完整消息事件（供持久化/记忆记录等下游消费）
        self.event_bus.publish(
            Event(
                type=SystemEvent.THINK_ENGINE_INITIATIVE,
                source="initiative_timer",
                data={
                    "message": message,
                    "timer_id": timer_id,
                    "pending_summary": pending_summary,
                    "thought": thought,
                },
            )
        )
        self.event_bus.publish(
            Event(
                type=SystemEvent.MESSAGE_SENT,
                source="initiative_timer",
                data={
                    "content": message,
                    "initiative": True,
                    "timer_id": timer_id,
                    "pending_summary": pending_summary,
                },
            )
        )
        logger.info(
            f"[Agent] 主动消息已发送，timer_id={timer_id}, 长度={len(message)}, "
            f"内容: {message[:80]}..."
        )

        # 主动发言成功：递增计数，并在未达上限时继续调度下一轮主动定时器
        self._ensure_initiative_timer().increment_consecutive_initiative_count()
        if (
            self._initiative_timer is not None
            and not self._initiative_timer._has_reached_initiative_limit()
        ):
            logger.debug("[Agent] 未达连续主动上限，继续调度下一轮主动定时器")
            self._last_initiative_timer_payload = await self.schedule_initiative_timer(message)

        return {
            "sent": True,
            "timer_id": timer_id,
            "pending_summary": pending_summary,
            "message": message,
            "thought": thought,
        }

    async def discard_initiative_timer(
        self, *, reason: str = "discarded", source: str = "system"
    ) -> dict | None:
        if self._initiative_timer is None:
            return None
        self._last_initiative_timer_payload = None
        if source == "user":
            self._initiative_timer.reset_consecutive_initiative_count()
        return await self._initiative_timer.discard(reason=reason, source=source)

    def current_initiative_timer(self) -> dict | None:
        if self._initiative_timer is None:
            return None
        return self._initiative_timer.current_payload()

    def initiative_hesitation_status(self) -> dict:
        return {
            "enabled": self.config.initiative_timer.hesitation_enabled,
            "max_rounds": self.config.initiative_timer.hesitation_max_rounds,
            "delay_seconds": self.config.initiative_timer.hesitation_delay_seconds,
        }

    def set_initiative_hesitation_enabled(self, enabled: bool, *, persist: bool = True) -> dict:
        self.config.initiative_timer.hesitation_enabled = bool(enabled)
        config_path: str | None = None
        if persist:
            path = ConfigLoader.set_initiative_hesitation_enabled(
                getattr(self, "config_file", None),
                bool(enabled),
            )
            config_path = str(path)
        payload = self.initiative_hesitation_status()
        payload["config_path"] = config_path
        return payload

    async def update_initiative_timer(
        self,
        *,
        timer_id: str | None = None,
        delay_seconds: int | float | None = None,
        due_at: str | None = None,
        pending_summary: str | None = None,
    ) -> dict:
        payload = await self._ensure_initiative_timer().update(
            timer_id=timer_id,
            delay_seconds=delay_seconds,
            due_at=due_at,
            pending_summary=pending_summary,
        )
        self._last_initiative_timer_payload = payload
        return payload

    async def cancel_initiative_timer(
        self, *, timer_id: str | None = None, reason: str = "cancelled"
    ) -> dict:
        self._last_initiative_timer_payload = None
        return await self._ensure_initiative_timer().cancel(timer_id=timer_id, reason=reason)

    async def trigger_initiative_timer(self, *, timer_id: str | None = None) -> dict:
        self._last_initiative_timer_payload = None
        return await self._ensure_initiative_timer().trigger(timer_id=timer_id)

    async def _on_shutdown(self) -> None:
        if self._generate_response_subscription_id is not None:
            self.event_bus.unsubscribe(self._generate_response_subscription_id)
            self._generate_response_subscription_id = None
        self.event_bus.publish(Event(type=SystemEvent.AGENT_SHUTDOWN, source="agent"))

        # 关机后普通自动保存不再提交后台任务；最终保存由 save_immediately 直接落盘。
        self.save_coordinator.set_shutting_down(True)

        if self._think_engine:
            await self._think_engine.stop()

        if self._initiative_timer:
            await self._initiative_timer.shutdown()

        if self._background_manager:
            await self._background_manager.stop(wait=True)

        try:
            await self.save_coordinator.save_immediately(self.working_memory)
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
        manager.register_persistence_worker(PersistenceWorker(self.session_manager.persistence))
        return manager

    @property
    def metrics(self) -> dict:
        return {
            "event_bus": self.event_bus.stats,
            "app": self.metrics_listeners.metrics if hasattr(self, "metrics_listeners") else {},
        }
