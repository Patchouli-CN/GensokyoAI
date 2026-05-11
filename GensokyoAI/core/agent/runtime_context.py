"""Agent 运行时组件容器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..events import EventBus
from ...memory.episodic import EpisodicMemoryManager
from ...session.manager import SessionManager
from ...tools.build_service import ToolBuildService
from ...tools.executor import ToolExecutor
from ...tools.registry import ToolRegistry
from .model_client import ModelClient
from .model_registry import ModelRegistryService

if TYPE_CHECKING:
    from .action_executor import ActionExecutor
    from .action_planner import ActionPlanner
    from .lifecycle import LifecycleManager
    from .message_builder import MessageBuilder
    from .response_handler import ResponseHandler
    from .save_coordinator import SaveCoordinator
    from .think_engine import ThinkEngine


@dataclass(slots=True)
class AgentRuntimeContext:
    """保存 Agent 初始化阶段装配出的核心组件。"""

    event_bus: EventBus
    memory_base_path: Path
    model_client: ModelClient
    episodic_memory: EpisodicMemoryManager
    tool_registry: ToolRegistry
    tool_executor: ToolExecutor
    tool_build_service: ToolBuildService
    model_registry_service: ModelRegistryService
    session_manager: SessionManager


@dataclass(slots=True)
class AgentLazyComponents:
    """保存 Agent 启动前后按需创建的行为组件。"""

    message_builder: "MessageBuilder | None" = None
    save_coordinator: "SaveCoordinator | None" = None
    response_handler: "ResponseHandler | None" = None
    lifecycle: "LifecycleManager | None" = None
    think_engine: "ThinkEngine | None" = None
    action_planner: "ActionPlanner | None" = None
    action_executor: "ActionExecutor | None" = None


@dataclass(slots=True)
class AgentBootstrapState:
    """Agent 初始化阶段装配出的完整状态。"""

    runtime_context: AgentRuntimeContext
    lazy_components: AgentLazyComponents = field(default_factory=AgentLazyComponents)
