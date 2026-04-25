"""Claude (Anthropic) Provider 实现

支持 Anthropic Claude 系列模型 API。
"""

# GensokyoAI/core/agent/providers/claude_provider.py

import json
from typing import Any, AsyncIterator, TYPE_CHECKING

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
        system_prompt, claude_messages = self._convert_messages_to_claude(messages)
        max_tokens = options.get("num_predict") or options.get("max_tokens", 2048)

        call_kwargs: dict = {
            "model": model,
            "messages": claude_messages,
            "max_tokens": max_tokens,
            "temperature": options.get("temperature", 0.7),
            "top_p": options.get("top_p", 0.9),
        }

        if system_prompt:
            call_kwargs["system"] = system_prompt

        if tools:
            call_kwargs["tools"] = self._convert_tools_to_claude(tools)

        # Claude extended thinking 支持。
        # Anthropic 要求 thinking budget 小于 max_tokens；开启 thinking 时移除采样参数以避免模型族兼容问题。
        if kwargs.get("think"):
            thinking_budget = self._get_thinking_budget(options, max_tokens)
            if thinking_budget:
                call_kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": thinking_budget,
                }
                call_kwargs.pop("temperature", None)
                call_kwargs.pop("top_p", None)

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
        system_prompt, claude_messages = self._convert_messages_to_claude(messages)
        max_tokens = options.get("num_predict") or options.get("max_tokens", 2048)

        call_kwargs: dict = {
            "model": model,
            "messages": claude_messages,
            "max_tokens": max_tokens,
            "temperature": options.get("temperature", 0.7),
            "top_p": options.get("top_p", 0.9),
        }

        if system_prompt:
            call_kwargs["system"] = system_prompt

        if tools:
            call_kwargs["tools"] = self._convert_tools_to_claude(tools)

        # Claude extended thinking 支持。
        if kwargs.get("think"):
            thinking_budget = self._get_thinking_budget(options, max_tokens)
            if thinking_budget:
                call_kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": thinking_budget,
                }
                call_kwargs.pop("temperature", None)
                call_kwargs.pop("top_p", None)

        # 工具调用 / thinking 累积；Claude 流式事件以 content block index 区分多个 block。
        tool_blocks: dict[int, dict[str, Any]] = {}
        thinking_parts: list[str] = []

        async with self._client.messages.stream(**call_kwargs) as stream:
            async for event in stream:
                # 文本内容
                if hasattr(event, "type"):
                    if event.type == "content_block_start":
                        block = event.content_block
                        index = getattr(event, "index", 0)
                        if getattr(block, "type", "") == "tool_use":
                            tool_blocks[index] = {
                                "id": getattr(block, "id", ""),
                                "name": getattr(block, "name", ""),
                                "input_json": "",
                            }

                    elif event.type == "content_block_delta":
                        delta = event.delta
                        index = getattr(event, "index", 0)
                        if hasattr(delta, "type"):
                            if delta.type == "text_delta":
                                yield StreamChunk(content=delta.text)
                            elif delta.type == "thinking_delta":
                                thinking_parts.append(getattr(delta, "thinking", ""))
                            elif delta.type == "input_json_delta" and index in tool_blocks:
                                tool_blocks[index]["input_json"] += getattr(
                                    delta, "partial_json", ""
                                )

                    elif event.type == "message_stop" and tool_blocks:
                        unified_tool_calls: list[ToolCall] = []
                        for _index, tool_data in sorted(tool_blocks.items()):
                            try:
                                args = (
                                    json.loads(tool_data["input_json"])
                                    if tool_data["input_json"]
                                    else {}
                                )
                            except json.JSONDecodeError:
                                args = {}

                            unified_tool_calls.append(
                                ToolCall(
                                    id=tool_data.get("id", ""),
                                    provider="claude",
                                    function=ToolCallFunction(
                                        name=tool_data.get("name", ""),
                                        arguments=args,
                                        provider="claude",
                                    ),
                                )
                            )

                        unified_msg = UnifiedMessage(
                            role="assistant",
                            content="",
                            tool_calls=unified_tool_calls,
                        )
                        yield StreamChunk(
                            is_tool_call=True,
                            tool_info={
                                "message": unified_msg,
                                "thinking": "".join(thinking_parts) if thinking_parts else None,
                            },
                        )

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
    def _get_thinking_budget(options: dict, max_tokens: int) -> int | None:
        """获取 Claude extended thinking 的 token 预算。"""
        budget = options.get("thinking_budget_tokens") or options.get("thinking_budget")
        if budget is not None:
            budget = int(budget)
            return budget if 0 < budget < max_tokens else None

        # Anthropic thinking budget 必须小于 max_tokens；max_tokens 太低时不自动开启，避免 400。
        if max_tokens <= 1024:
            logger.warning(
                "Claude extended thinking 已请求，但 max_tokens <= 1024，跳过 thinking 参数"
            )
            return None
        return min(max_tokens - 1, max(1024, max_tokens // 2))

    @classmethod
    def _convert_messages_to_claude(cls, messages: list[dict]) -> tuple[str, list[dict]]:
        """
        将项目内部 / OpenAI 风格 messages 转换为 Claude Messages API 格式。

        Claude 要求：
        - system 作为顶层 system 参数传入；
        - assistant 工具调用必须是 assistant content 中的 tool_use block；
        - 工具结果必须是紧随其后的 user content 中的 tool_result block；
        - 不支持 OpenAI 的 role=tool。
        """
        system_parts: list[str] = []
        claude_messages: list[dict] = []

        pending_tool_results: list[dict] = []

        def flush_tool_results() -> None:
            if pending_tool_results:
                # Claude 要求多个 tool_result block 在同一 user 消息中置于 content 数组最前面。
                claude_messages.append({"role": "user", "content": pending_tool_results.copy()})
                pending_tool_results.clear()

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "system":
                if content:
                    system_parts.append(str(content))
                continue

            if role == "tool":
                pending_tool_results.append(cls._convert_tool_result_block(msg))
                continue

            flush_tool_results()

            if role == "assistant":
                claude_messages.append(cls._convert_assistant_message(msg))
            elif role == "user":
                claude_messages.append({"role": "user", "content": content})
            else:
                # Claude 只接受 user/assistant；未知角色降级为 user 文本。
                claude_messages.append({"role": "user", "content": str(content)})

        flush_tool_results()

        system_prompt = "\n\n".join(system_parts) if system_parts else ""
        return system_prompt, claude_messages

    @classmethod
    def _convert_assistant_message(cls, msg: dict) -> dict:
        """转换 assistant 消息，保留 tool_use blocks。"""
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            return {"role": "assistant", "content": content}

        blocks: list[dict] = []
        if content:
            blocks.append({"type": "text", "text": str(content)})

        for tool_call in tool_calls:
            tool_id, name, arguments = cls._extract_tool_call(tool_call)
            blocks.append(
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": name,
                    "input": arguments,
                }
            )

        return {"role": "assistant", "content": blocks}

    @staticmethod
    def _convert_tool_result_block(msg: dict) -> dict:
        """将 OpenAI role=tool 消息转换为 Claude tool_result content block。"""
        content = msg.get("content", "")
        tool_result: dict = {
            "type": "tool_result",
            "tool_use_id": msg.get("tool_call_id", "") or msg.get("id", ""),
        }
        if content:
            tool_result["content"] = str(content)
        if msg.get("is_error") or str(content).startswith(("错误:", "调用出错啦:")):
            tool_result["is_error"] = True
        return tool_result

    @staticmethod
    def _extract_tool_call(tool_call) -> tuple[str, str, dict]:
        """从 ToolCall 对象或 OpenAI 风格 dict 中提取 Claude tool_use 所需字段。"""
        if isinstance(tool_call, dict):
            function = tool_call.get("function", {}) or {}
            args = function.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args else {}
                except json.JSONDecodeError:
                    args = {}
            return tool_call.get("id", ""), function.get("name", ""), args or {}

        function = getattr(tool_call, "function", None)
        return (
            getattr(tool_call, "id", ""),
            getattr(function, "name", "") if function else "",
            getattr(function, "arguments", {}) if function else {},
        )

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
                        id=getattr(block, "id", ""),
                        provider="claude",
                        function=ToolCallFunction(
                            name=block.name,
                            arguments=block.input or {},
                            provider="claude",
                        ),
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
