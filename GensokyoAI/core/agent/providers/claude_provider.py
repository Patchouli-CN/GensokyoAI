"""Claude (Anthropic) Provider 实现

支持 Anthropic Claude 系列模型 API。
"""

# GensokyoAI/core/agent/providers/claude_provider.py

from typing import AsyncIterator, TYPE_CHECKING

from .base import BaseProvider
from ..types import (
    UnifiedResponse,
    UnifiedMessage,
    UnifiedEmbeddingResponse,
    StreamChunk,
    ToolCall,
    ToolCallFunction,
)
from ....utils.logger import logger

if TYPE_CHECKING:
    from ...config import ModelConfig


class ClaudeProvider(BaseProvider):
    """
    Anthropic Claude Provider

    使用 anthropic SDK 调用 Claude 系列模型。
    注意：Claude 的消息格式与 OpenAI 有所不同，需要特殊处理。
    """

    def __init__(self, config: "ModelConfig"):
        super().__init__(config)
        self._client = self._build_client()
        logger.debug(f"ClaudeProvider 初始化完成，model: {config.name}")

    def _build_client(self):
        """构建 Anthropic 异步客户端"""
        try:
            from anthropic import AsyncAnthropic
        except ImportError:
            raise ImportError(
                "使用 Claude Provider 需要安装 anthropic 包: pip install anthropic\n"
                "或者: pip install gensokyoai[claude]"
            )

        kwargs = {}
        if self.config.api_key:
            kwargs["api_key"] = self.config.api_key
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url

        return AsyncAnthropic(**kwargs)

    async def chat(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        options: dict | None = None,
        **kwargs,
    ) -> UnifiedResponse:
        """非流式调用 Claude API"""
        options = options or {}
        system_prompt, claude_messages = self._separate_system_messages(messages)

        call_kwargs: dict = {
            "model": model,
            "messages": claude_messages,
            "max_tokens": options.get("num_predict") or options.get("max_tokens", 2048),
            "temperature": options.get("temperature", 0.7),
            "top_p": options.get("top_p", 0.9),
        }

        if system_prompt:
            call_kwargs["system"] = system_prompt

        if tools:
            call_kwargs["tools"] = self._convert_tools_to_claude(tools)

        # Claude extended thinking 支持
        if kwargs.get("think"):
            call_kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": options.get("num_predict", 2048),
            }

        response = await self._client.messages.create(**call_kwargs)
        return self._convert_response(response)

    async def chat_stream(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        options: dict | None = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """流式调用 Claude API"""
        options = options or {}
        system_prompt, claude_messages = self._separate_system_messages(messages)

        call_kwargs: dict = {
            "model": model,
            "messages": claude_messages,
            "max_tokens": options.get("num_predict") or options.get("max_tokens", 2048),
            "temperature": options.get("temperature", 0.7),
            "top_p": options.get("top_p", 0.9),
        }

        if system_prompt:
            call_kwargs["system"] = system_prompt

        if tools:
            call_kwargs["tools"] = self._convert_tools_to_claude(tools)

        # Claude extended thinking 支持
        if kwargs.get("think"):
            call_kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": options.get("num_predict", 2048),
            }

        # 工具调用累积
        tool_name = ""
        tool_input_json = ""
        in_tool_use = False

        async with self._client.messages.stream(**call_kwargs) as stream:
            async for event in stream:
                # 文本内容
                if hasattr(event, "type"):
                    if event.type == "content_block_start":
                        block = event.content_block
                        if hasattr(block, "type") and block.type == "tool_use":
                            in_tool_use = True
                            tool_name = block.name
                            tool_input_json = ""

                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if hasattr(delta, "type"):
                            if delta.type == "text_delta":
                                yield StreamChunk(content=delta.text)
                            elif delta.type == "input_json_delta":
                                tool_input_json += delta.partial_json

                    elif event.type == "content_block_stop" and in_tool_use:
                        import json

                        try:
                            args = json.loads(tool_input_json) if tool_input_json else {}
                        except json.JSONDecodeError:
                            args = {}

                        unified_msg = UnifiedMessage(
                            role="assistant",
                            content="",
                            tool_calls=[
                                ToolCall(
                                    function=ToolCallFunction(
                                        name=tool_name,
                                        arguments=args,
                                    )
                                )
                            ],
                        )
                        yield StreamChunk(
                            is_tool_call=True,
                            tool_info={"message": unified_msg},
                        )
                        in_tool_use = False

    async def embeddings(
        self,
        model: str,
        prompt: str,
        **kwargs,
    ) -> UnifiedEmbeddingResponse:
        """Claude 不支持 embeddings"""
        raise NotImplementedError("Anthropic Claude 不提供 embeddings API")

    def update_config(self, config: "ModelConfig") -> None:
        """更新配置并重建客户端"""
        super().update_config(config)
        self._client = self._build_client()
        logger.info(f"ClaudeProvider 配置已更新")

    # ==================== 转换工具方法 ====================

    @staticmethod
    def _separate_system_messages(messages: list[dict]) -> tuple[str, list[dict]]:
        """
        分离 system 消息

        Claude API 要求 system 消息单独传入，不能放在 messages 列表中。
        """
        system_parts = []
        other_messages = []

        for msg in messages:
            if msg.get("role") == "system":
                system_parts.append(msg.get("content", ""))
            else:
                other_messages.append(msg)

        system_prompt = "\n\n".join(system_parts) if system_parts else ""
        return system_prompt, other_messages

    def _convert_response(self, response) -> UnifiedResponse:
        """将 Claude Message 转换为 UnifiedResponse"""
        content_parts = []
        tool_calls = []
        thinking = None

        for block in response.content:
            if block.type == "text":
                content_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        function=ToolCallFunction(
                            name=block.name,
                            arguments=block.input or {},
                        )
                    )
                )
            elif block.type == "thinking":
                thinking = block.thinking

        return UnifiedResponse(
            message=UnifiedMessage(
                role="assistant",
                content="".join(content_parts),
                tool_calls=tool_calls if tool_calls else None,
            ),
            model=response.model or "",
            done=True,
            thinking=thinking,
        )

    @staticmethod
    def _convert_tools_to_claude(tools: list[dict]) -> list[dict]:
        """
        将 Ollama/OpenAI 格式的工具定义转换为 Claude 格式

        Claude 格式:
          {"name": "...", "description": "...", "input_schema": {...}}

        OpenAI/Ollama 格式:
          {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}
        """
        claude_tools = []
        for tool in tools:
            if "function" in tool:
                func = tool["function"]
                claude_tools.append(
                    {
                        "name": func.get("name", ""),
                        "description": func.get("description", ""),
                        "input_schema": func.get("parameters", {}),
                    }
                )
            else:
                # 已经是 Claude 格式
                claude_tools.append(tool)
        return claude_tools
