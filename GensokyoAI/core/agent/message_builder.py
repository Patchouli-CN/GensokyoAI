"""消息构建器 - 构建发送给模型的消息列表"""

# GensokyoAI/core/agent/message_builder.py

from typing import TYPE_CHECKING

from ...tools.registry import ToolRegistry

if TYPE_CHECKING:
    from ...memory.working import WorkingMemoryManager
    from ...memory.episodic import EpisodicMemoryManager
    from ...memory.semantic import SemanticMemoryManager


class MessageBuilder:
    """
    消息构建器 - 构建发送给模型的消息列表

    职责：
    - 组装系统提示词
    - 添加情景记忆（历史摘要）
    - 添加语义记忆（相关知识）
    - 添加工作记忆（当前对话）
    - 构建工具调用后的继续对话消息
    """

    def __init__(
        self,
        system_prompt: str,
        working_memory: "WorkingMemoryManager",
        episodic_memory: "EpisodicMemoryManager",
        semantic_memory: "SemanticMemoryManager",
        tool_registry: ToolRegistry | None = None,
        tool_enabled: bool = False,
    ):
        """
        初始化消息构建器

        Args:
            system_prompt: 基础系统提示词
            working_memory: 工作记忆管理器
            episodic_memory: 情景记忆管理器
            semantic_memory: 语义记忆管理器
            tool_registry: 工具注册中心（用于生成工具说明）
            tool_enabled: 是否启用工具
        """
        self._system_prompt = system_prompt
        self._working_memory = working_memory
        self._episodic_memory = episodic_memory
        self._semantic_memory = semantic_memory
        self._tool_registry = tool_registry
        self._tool_enabled = tool_enabled

    @property
    def system_prompt(self) -> str:
        """获取系统提示词（包含工具说明）"""
        prompt = self._system_prompt

        # 添加工具说明
        if self._tool_enabled and self._tool_registry:
            if tools := self._tool_registry.list():
                tools_desc = "\n\n【可用工具】\n"
                tools_desc += "\n".join(f"- {t.name}: {t.description}" for t in tools)
                prompt += tools_desc
                prompt += (
                    "\n当需要获取外部信息时，请调用相应的工具。调用工具后，将结果整合到回复中。"
                )

        return prompt

    def build(self, user_input: str) -> list[dict[str, str]]:
        """
        构建完整消息列表

        Args:
            user_input: 用户输入

        Returns:
            消息列表，格式为 [{"role": "...", "content": "..."}]
        """
        messages: list[dict[str, str]] = [{"role": "system", "content": self.system_prompt}]

        # 情景记忆（历史摘要）
        if episodic_context := self._episodic_memory.get_relevant_context(user_input):
            messages.append(
                {
                    "role": "system",
                    "content": "【历史记忆摘要】\n" + "\n".join(episodic_context),
                }
            )

        # 语义记忆（相关记忆）
        if semantic_context := self._semantic_memory.get_relevant_context(user_input):
            messages.append(
                {
                    "role": "system",
                    "content": "【相关记忆】\n" + "\n".join(semantic_context),
                }
            )

        # 工作记忆（当前对话）
        messages.extend(self._working_memory.get_context())

        # 当前用户输入
        messages.append({"role": "user", "content": user_input})

        return messages

    def build_continuation(self) -> list[dict[str, str]]:
        """
        构建工具调用后的继续对话消息

        用于模型调用工具后，带着工具结果继续生成回复

        Returns:
            消息列表
        """
        messages: list[dict[str, str]] = [{"role": "system", "content": self.system_prompt}]
        messages.extend(self._working_memory.get_context())
        messages.append(
            {
                "role": "system",
                "content": "工具调用已完成，请自然地将结果信息融入你的回复中，保持角色风格。",
            }
        )
        return messages

    def update_system_prompt(self, system_prompt: str) -> None:
        """
        更新系统提示词（例如切换角色时）

        Args:
            system_prompt: 新的系统提示词
        """
        self._system_prompt = system_prompt
