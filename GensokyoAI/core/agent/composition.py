"""Agent 组件装配。"""

from __future__ import annotations

from ..config import AppConfig
from ..events import EventBus
from ...memory.episodic import EpisodicMemoryManager
from ...session.manager import SessionManager
from ...tools.build_service import ToolBuildService
from ...tools.executor import ToolExecutor
from ...tools.registry import ToolRegistry
from .model_client import ModelClient
from .model_registry import ModelRegistryService
from .runtime_context import AgentBootstrapState, AgentRuntimeContext


class AgentComposition:
    """负责创建 Agent 运行所需的基础组件。"""

    def __init__(self, config: AppConfig, character_name: str) -> None:
        self.config = config
        self.character_name = character_name

    def build(self) -> AgentRuntimeContext:
        """装配核心运行时组件。"""
        event_bus = EventBus(enable_trace=self.config.event_trace_enabled)
        memory_base_path = self.config.session.save_path
        model_client = ModelClient(
            self.config.model,
            event_bus=event_bus,
            embedding_config=self.config.embedding,
        )
        episodic_memory = EpisodicMemoryManager(
            self.config.memory,
            self.character_name,
            None,
            model_client,
        )
        tool_registry = ToolRegistry()
        tool_executor = ToolExecutor(tool_registry, event_bus=event_bus)
        tool_build_service = ToolBuildService(tool_registry)
        model_registry_service = ModelRegistryService()
        session_manager = SessionManager(
            self.config.session,
            self.character_name,
            working_max_turns=self.config.memory.working_max_turns,
        )

        return AgentRuntimeContext(
            event_bus=event_bus,
            memory_base_path=memory_base_path,
            model_client=model_client,
            episodic_memory=episodic_memory,
            tool_registry=tool_registry,
            tool_executor=tool_executor,
            tool_build_service=tool_build_service,
            model_registry_service=model_registry_service,
            session_manager=session_manager,
        )

    def bootstrap(self) -> AgentBootstrapState:
        """装配 Agent 初始化阶段所需的完整状态。"""
        return AgentBootstrapState(runtime_context=self.build())
