"""OpenAI 兼容 Provider 实现

支持所有 OpenAI 兼容 API，包括：
- OpenAI 官方
- Deepseek
- SiliconFlow
- vLLM
- Groq
- 本地 llama.cpp server
- 任何 OpenAI 兼容的第三方服务
"""

# GensokyoAI/core/agent/providers/openai_provider.py

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


class OpenAIProvider(BaseProvider):
    """
    OpenAI 兼容 Provider

    使用 openai SDK 调用所有兼容 OpenAI Chat Completions API 的服务。
    通过 base_url 配置可以指向任何兼容端点。
    """

    def __init__(self, config: "ModelConfig"):
        super().__init__(config)
        self._client = self._build_client()
        logger.debug(
            f"OpenAIProvider 初始化完成，base_url: {config.base_url}, model: {config.name}"
        )

    def _build_client(self):
        """构建 OpenAI 异步客户端"""
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError(
                "使用 OpenAI Provider 需要安装 openai 包: pip install openai\n"
                "或者: pip install gensokyoai[openai]"
            )

        kwargs = {}
        if self.config.api_key:
            kwargs["api_key"] = self.config.api_key
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url

        return AsyncOpenAI(**kwargs)

    # ==================== 消息清洗 ====================

    @staticmethod
    def _clean_messages(messages: list[dict]) -> list[dict]:
        """
        迭代清洗消息列表，移除所有 V4/V3 特有的 reasoning_content 字段。
        使用显式栈代替递归，避免深层嵌套时栈溢出。
        """
        import copy
        
        cleaned = copy.deepcopy(messages)
        stack = [cleaned]
        
        while stack:
            obj = stack.pop()
            
            if isinstance(obj, dict):
                obj.pop("reasoning_content", None)
                stack.extend(obj.values())
            elif isinstance(obj, list):
                stack.extend(obj)
        
        return cleaned

    # ==================== 核心 API ====================

    async def chat(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        options: dict | None = None,
        **kwargs,
    ) -> UnifiedResponse:
        """非流式调用 OpenAI 兼容 API"""
        options = options or {}

        call_kwargs: dict = {
            "model": model,
            "messages": self._clean_messages(messages),
            "temperature": options.get("temperature", 0.7),
            "top_p": options.get("top_p", 0.9),
        }

        # max_tokens 映射：优先使用 max_completion_tokens（新版 API 推荐），回退到 max_tokens
        max_tokens = (
            options.get("max_completion_tokens")
            or options.get("num_predict")
            or options.get("max_tokens")
        )
        if max_tokens:
            call_kwargs["max_completion_tokens"] = max_tokens

        # 工具支持
        if tools:
            call_kwargs["tools"] = self._convert_tools_to_openai(tools)
            if tool_choice := options.get("tool_choice"):
                call_kwargs["tool_choice"] = tool_choice

        response = await self._client.chat.completions.create(**call_kwargs)

        return self._convert_response(response)

    async def chat_stream(  # type: ignore
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        options: dict | None = None,
        extra_body: dict | None = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """流式调用 OpenAI 兼容 API"""
        options = options or {}

        call_kwargs: dict = {
            "model": model,
            "messages": self._clean_messages(messages),
            "temperature": options.get("temperature", 0.7),
            "top_p": options.get("top_p", 0.9),
            "stream": True,
        }

        # 应用 extra_body（如 thinking 模式控制）
        if extra_body:
            call_kwargs["extra_body"] = extra_body

        # max_tokens 映射
        max_tokens = (
            options.get("max_completion_tokens")
            or options.get("num_predict")
            or options.get("max_tokens")
        )
        if max_tokens:
            call_kwargs["max_completion_tokens"] = max_tokens

        if tools:
            call_kwargs["tools"] = self._convert_tools_to_openai(tools)
            if tool_choice := options.get("tool_choice"):
                call_kwargs["tool_choice"] = tool_choice

        # 流式工具调用累积器（不存 reasoning_content，防止 V4 要求回传）
        tool_calls_acc: dict[int, dict] = {}

        stream = await self._client.chat.completions.create(**call_kwargs)

        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                continue

            # 处理工具调用
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {
                            "id": "",
                            "name": "",
                            "arguments": "",
                        }
                    if tc.id:
                        tool_calls_acc[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls_acc[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls_acc[idx]["arguments"] += tc.function.arguments

            # 处理内容（if 不是 elif，V4 可能同时返回 tool_calls 和 content）
            if delta.content:
                yield StreamChunk(content=delta.content)

            # 检查结束
            finish_reason = chunk.choices[0].finish_reason if chunk.choices else None
            if finish_reason == "tool_calls" and tool_calls_acc:
                import json

                unified_tool_calls = []
                for _idx, tc_data in sorted(tool_calls_acc.items()):
                    try:
                        args = json.loads(tc_data["arguments"]) if tc_data["arguments"] else {}
                    except json.JSONDecodeError:
                        args = {}
                    unified_tool_calls.append(
                        ToolCall(
                            id=tc_data.get("id", ""),
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
        """获取文本向量"""
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
        logger.info(f"OpenAIProvider 配置已更新，base_url: {config.base_url}")

    # ==================== 转换工具方法 ====================

    def _convert_response(self, response) -> UnifiedResponse:
        """将 OpenAI ChatCompletion 转换为 UnifiedResponse"""
        choice = response.choices[0] if response.choices else None
        if not choice:
            return UnifiedResponse(model=response.model or "")

        message = choice.message
        tool_calls = None

        if message.tool_calls:
            import json

            tool_calls = []
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(
                    ToolCall(
                        id=tc.id or "",
                        function=ToolCallFunction(
                            name=tc.function.name or "",
                            arguments=args,
                        ),
                    )
                )

        thinking = None
        # 只记录 reasoning_content 用于调试，不存到 UnifiedMessage 里回传
        if hasattr(message, "reasoning_content") and message.reasoning_content:
            thinking = message.reasoning_content
            logger.debug(f"V4 思维链已记录（长度: {len(thinking)}），不回传")

        return UnifiedResponse(
            message=UnifiedMessage(
                role=message.role or "assistant",
                content=message.content or "",
                tool_calls=tool_calls,
            ),
            model=response.model or "",
            done=True,
            thinking=thinking,
        )

    @staticmethod
    def _convert_tools_to_openai(tools: list[dict]) -> list[dict]:
        """
        验证并规范化工具定义为 OpenAI Chat Completions 格式

        期望输入格式（由 ToolDefinition.to_openai_schema() 生成）:
          {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}

        如果输入缺少外层包装，会自动适配。
        """
        openai_tools = []
        for tool in tools:
            if "type" in tool and "function" in tool:
                openai_tools.append(tool)
            else:
                openai_tools.append({"type": "function", "function": tool})
        return openai_tools
