"""OpenAI Responses API Provider 实现

专用于 OpenAI 官方 Responses API（/v1/responses），提供：
- 更优的推理模型性能（GPT-5 等）
- 内置工具支持（web_search、code_interpreter 等）
- 原生多轮对话状态管理（previous_response_id）
- 更低的成本（更好的缓存利用率）

注意：此 Provider 仅适用于 OpenAI 官方 API，不兼容第三方 OpenAI 兼容服务。
对于 Deepseek/SiliconFlow/vLLM/Groq 等第三方服务，请使用 openai Provider
（Chat Completions API）。
"""

# GensokyoAI/core/agent/providers/openai_responses_provider.py

import json
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


class OpenAIResponsesProvider(BaseProvider):
    """
    OpenAI Responses API Provider

    使用 openai SDK 调用 OpenAI Responses API（/v1/responses）。
    推荐用于 OpenAI 官方 API，可获得更好的推理性能和更低的成本。
    """

    def __init__(self, config: "ModelConfig"):
        super().__init__(config)
        self._client = self._build_client()
        logger.debug(
            f"OpenAIResponsesProvider 初始化完成，base_url: {config.base_url}, model: {config.name}"
        )

    def _build_client(self):
        """构建 OpenAI 异步客户端"""
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError(
                "使用 OpenAI Responses Provider 需要安装 openai 包: pip install openai\n"
                "或者: pip install gensokyoai[openai]"
            )

        kwargs = {}
        if self.config.api_key:
            kwargs["api_key"] = self.config.api_key
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url

        return AsyncOpenAI(**kwargs)

    # ==================== 核心 API ====================

    async def chat(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        options: dict | None = None,
        **kwargs,
    ) -> UnifiedResponse:
        """非流式调用 OpenAI Responses API"""
        options = options or {}

        # 从 messages 中分离 system/developer 指令和对话内容
        instructions, input_items = self._convert_messages_to_input(messages)

        call_kwargs: dict = {
            "model": model,
            "input": input_items,
        }

        # 设置 instructions（系统提示词）
        if instructions:
            call_kwargs["instructions"] = instructions

        # temperature 和 top_p
        temperature = options.get("temperature", 0.7)
        top_p = options.get("top_p", 0.9)
        call_kwargs["temperature"] = temperature
        call_kwargs["top_p"] = top_p

        # max_output_tokens（Responses API 使用此参数名）
        max_tokens = (
            options.get("max_completion_tokens")
            or options.get("num_predict")
            or options.get("max_tokens")
        )
        if max_tokens:
            call_kwargs["max_output_tokens"] = max_tokens

        # 工具支持
        if tools:
            call_kwargs["tools"] = self._convert_tools_to_responses(tools)
            if tool_choice := options.get("tool_choice"):
                call_kwargs["tool_choice"] = tool_choice

        # 推理配置（reasoning effort）
        if reasoning := options.get("reasoning"):
            call_kwargs["reasoning"] = reasoning

        # store 配置（默认不存储，因为项目自己管理对话状态）
        call_kwargs["store"] = options.get("store", False)

        response = await self._client.responses.create(**call_kwargs)

        return self._convert_response(response)

    async def chat_stream(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        options: dict | None = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """流式调用 OpenAI Responses API"""
        options = options or {}

        # 从 messages 中分离指令和对话内容
        instructions, input_items = self._convert_messages_to_input(messages)

        call_kwargs: dict = {
            "model": model,
            "input": input_items,
            "stream": True,
        }

        if instructions:
            call_kwargs["instructions"] = instructions

        temperature = options.get("temperature", 0.7)
        top_p = options.get("top_p", 0.9)
        call_kwargs["temperature"] = temperature
        call_kwargs["top_p"] = top_p

        max_tokens = (
            options.get("max_completion_tokens")
            or options.get("num_predict")
            or options.get("max_tokens")
        )
        if max_tokens:
            call_kwargs["max_output_tokens"] = max_tokens

        if tools:
            call_kwargs["tools"] = self._convert_tools_to_responses(tools)
            if tool_choice := options.get("tool_choice"):
                call_kwargs["tool_choice"] = tool_choice

        if reasoning := options.get("reasoning"):
            call_kwargs["reasoning"] = reasoning

        call_kwargs["store"] = options.get("store", False)

        # 流式工具调用累积器：{output_index: {"call_id": ..., "name": ..., "arguments": ...}}
        tool_calls_acc: dict[int, dict] = {}

        stream = await self._client.responses.create(**call_kwargs)

        async for event in stream:
            event_type = event.type if hasattr(event, "type") else ""

            # 文本内容增量
            if event_type == "response.output_text.delta":
                delta_text = event.delta if hasattr(event, "delta") else ""
                if delta_text:
                    yield StreamChunk(content=delta_text)

            # 工具调用参数增量
            elif event_type == "response.function_call_arguments.delta":
                output_index = getattr(event, "output_index", 0)
                if output_index not in tool_calls_acc:
                    tool_calls_acc[output_index] = {
                        "call_id": "",
                        "name": "",
                        "arguments": "",
                    }
                delta = getattr(event, "delta", "")
                tool_calls_acc[output_index]["arguments"] += delta

            # 工具调用：新的输出项添加
            elif event_type == "response.output_item.added":
                item = getattr(event, "item", None)
                if item and getattr(item, "type", "") == "function_call":
                    output_index = getattr(event, "output_index", 0)
                    tool_calls_acc[output_index] = {
                        "call_id": getattr(item, "call_id", "") or getattr(item, "id", ""),
                        "name": getattr(item, "name", ""),
                        "arguments": getattr(item, "arguments", "") or "",
                    }

            # 工具调用参数完成
            elif event_type == "response.function_call_arguments.done":
                output_index = getattr(event, "output_index", 0)
                if output_index in tool_calls_acc:
                    # 更新完整的 arguments
                    tool_calls_acc[output_index]["arguments"] = getattr(event, "arguments", "")

            # 响应完成
            elif event_type == "response.completed":
                # 如果有工具调用，组装并 yield
                if tool_calls_acc:
                    unified_tool_calls = []
                    for _idx, tc_data in sorted(tool_calls_acc.items()):
                        try:
                            args = json.loads(tc_data["arguments"]) if tc_data["arguments"] else {}
                        except json.JSONDecodeError:
                            args = {}
                        unified_tool_calls.append(
                            ToolCall(
                                id=tc_data.get("call_id", ""),
                                function=ToolCallFunction(
                                    name=tc_data["name"],
                                    arguments=args,
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
                        tool_info={"message": unified_msg},
                    )

    async def embeddings(
        self,
        model: str,
        prompt: str,
        **kwargs,
    ) -> UnifiedEmbeddingResponse:
        """获取文本向量（Embeddings API 在两个 Provider 中是相同的）"""
        embed_kwargs: dict = {
            "model": model,
            "input": prompt,
        }

        if dimensions := kwargs.get("dimensions"):
            embed_kwargs["dimensions"] = dimensions

        if encoding_format := kwargs.get("encoding_format"):
            embed_kwargs["encoding_format"] = encoding_format

        response = await self._client.embeddings.create(**embed_kwargs)

        return UnifiedEmbeddingResponse(
            embedding=response.data[0].embedding,
            model=model,
        )

    def update_config(self, config: "ModelConfig") -> None:
        """更新配置并重建客户端"""
        super().update_config(config)
        self._client = self._build_client()
        logger.info(f"OpenAIResponsesProvider 配置已更新，base_url: {config.base_url}")

    # ==================== 转换方法 ====================

    @staticmethod
    def _convert_messages_to_input(
        messages: list[dict],
    ) -> tuple[str, list[dict]]:
        """
        将 Chat Completions 格式的 messages 转换为 Responses API 的 input + instructions

        Chat Completions 格式:
          [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}, ...]

        Responses API 格式:
          instructions="..." (系统提示词)
          input=[{"role": "user", "content": "..."}, ...] (对话内容)

        转换规则:
          - 第一个 system/developer 消息 → instructions 参数
          - 后续的 system 消息 → 合并到 instructions 或作为 developer 消息插入 input
          - user/assistant/tool 消息 → input 数组
        """
        instructions_parts: list[str] = []
        input_items: list[dict] = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role in ("system", "developer"):
                # 收集所有 system/developer 消息为 instructions
                if content:
                    instructions_parts.append(content)
            elif role == "assistant":
                input_items.append({"role": "assistant", "content": content})
            elif role == "user":
                input_items.append({"role": "user", "content": content})
            elif role == "tool":
                # tool 结果消息 → function_call_output Item
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": msg.get("tool_call_id", ""),
                        "output": content,
                    }
                )
            else:
                # 未知角色，作为 user 消息处理
                input_items.append({"role": "user", "content": content})

        instructions = "\n\n".join(instructions_parts) if instructions_parts else ""
        return instructions, input_items

    def _convert_response(self, response) -> UnifiedResponse:
        """将 Responses API 响应转换为 UnifiedResponse"""
        output = getattr(response, "output", []) or []

        # 提取文本内容和工具调用
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        thinking: str | None = None

        for item in output:
            item_type = getattr(item, "type", "")

            if item_type == "message":
                # 文本消息
                content_list = getattr(item, "content", []) or []
                for content_item in content_list:
                    content_type = getattr(content_item, "type", "")
                    if content_type == "output_text":
                        text = getattr(content_item, "text", "")
                        if text:
                            text_parts.append(text)

            elif item_type == "function_call":
                # 工具调用
                call_id = getattr(item, "call_id", "") or getattr(item, "id", "")
                name = getattr(item, "name", "")
                arguments_str = getattr(item, "arguments", "")
                try:
                    args = json.loads(arguments_str) if arguments_str else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(
                    ToolCall(
                        id=call_id,
                        function=ToolCallFunction(
                            name=name,
                            arguments=args,
                        ),
                    )
                )

            elif item_type == "reasoning":
                # 推理内容
                reasoning_content = getattr(item, "content", []) or []
                reasoning_texts = []
                for rc in reasoning_content:
                    if hasattr(rc, "text") and rc.text:
                        reasoning_texts.append(rc.text)
                if reasoning_texts:
                    thinking = "\n".join(reasoning_texts)

        # 组装文本
        full_text = "\n".join(text_parts) if text_parts else ""

        # 也尝试从 output_text 便捷属性获取
        if not full_text and hasattr(response, "output_text") and response.output_text:
            full_text = response.output_text

        return UnifiedResponse(
            message=UnifiedMessage(
                role="assistant",
                content=full_text,
                tool_calls=tool_calls if tool_calls else None,
            ),
            model=getattr(response, "model", "") or "",
            done=True,
            thinking=thinking,
        )

    @staticmethod
    def _convert_tools_to_responses(tools: list[dict]) -> list[dict]:
        """
        将 Chat Completions 格式的工具定义转换为 Responses API 格式

        Chat Completions 格式（外部标记多态）:
          {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}

        Responses API 格式（内部标记多态）:
          {"type": "function", "name": "...", "description": "...", "parameters": {...}}
        """
        responses_tools = []
        for tool in tools:
            if "function" in tool:
                # 从 Chat Completions 格式转换
                func_def = tool["function"]
                responses_tool: dict = {
                    "type": "function",
                    "name": func_def.get("name", ""),
                    "description": func_def.get("description", ""),
                    "parameters": func_def.get("parameters", {}),
                }
                # 保留 strict 设置
                if "strict" in func_def:
                    responses_tool["strict"] = func_def["strict"]
                responses_tools.append(responses_tool)
            elif "name" in tool and tool.get("type") == "function":
                # 已经是 Responses 格式
                responses_tools.append(tool)
            else:
                # 未知格式，尝试作为 Responses 格式使用
                responses_tools.append(tool)
        return responses_tools
