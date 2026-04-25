"""Google Gemini Provider 实现

支持 Google Gemini 系列模型 API。
"""

# GensokyoAI/core/agent/providers/gemini_provider.py

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


class GeminiProvider(BaseProvider):
    """
    Google Gemini Provider

    使用 google-genai SDK 调用 Gemini 系列模型。
    注意：Gemini 的消息角色和格式与 OpenAI 有所不同。
    """

    def __init__(self, config: "ModelConfig"):
        super().__init__(config)
        self._client = self._build_client()
        logger.debug(f"GeminiProvider 初始化完成，model: {config.name}")

    def _build_client(self):
        """构建 Gemini 客户端"""
        try:
            from google import genai
        except ImportError:
            raise ImportError(
                "使用 Gemini Provider 需要安装 google-genai 包: pip install google-genai\n"
                "或者: pip install gensokyoai[gemini]"
            )

        return genai.Client(api_key=self.config.api_key)

    async def chat(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        options: dict | None = None,
        **kwargs,
    ) -> UnifiedResponse:
        """非流式调用 Gemini API"""
        from google.genai import types as genai_types

        options = options or {}
        system_instruction, gemini_contents = self._convert_messages(messages)

        config_kwargs: dict = {
            "temperature": options.get("temperature", 0.7),
            "top_p": options.get("top_p", 0.9),
        }

        max_tokens = options.get("num_predict") or options.get("max_tokens")
        if max_tokens:
            config_kwargs["max_output_tokens"] = max_tokens

        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction

        gemini_tools = None
        if tools:
            gemini_tools = self._convert_tools_to_gemini(tools)
            config_kwargs["tools"] = gemini_tools

        config = genai_types.GenerateContentConfig(**config_kwargs)

        response = await self._client.aio.models.generate_content(
            model=model,
            contents=gemini_contents,
            config=config,
        )

        return self._convert_response(response, model)

    async def chat_stream(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        options: dict | None = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """流式调用 Gemini API"""
        from google.genai import types as genai_types

        options = options or {}
        system_instruction, gemini_contents = self._convert_messages(messages)

        config_kwargs: dict = {
            "temperature": options.get("temperature", 0.7),
            "top_p": options.get("top_p", 0.9),
        }

        max_tokens = options.get("num_predict") or options.get("max_tokens")
        if max_tokens:
            config_kwargs["max_output_tokens"] = max_tokens

        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction

        if tools:
            config_kwargs["tools"] = self._convert_tools_to_gemini(tools)

        config = genai_types.GenerateContentConfig(**config_kwargs)

        async for chunk in self._client.aio.models.generate_content_stream(
            model=model,
            contents=gemini_contents,
            config=config,
        ):
            if not chunk.candidates:
                continue

            candidate = chunk.candidates[0]
            if not candidate.content or not candidate.content.parts:
                continue

            for part in candidate.content.parts:
                if hasattr(part, "text") and part.text:
                    yield StreamChunk(content=part.text)
                elif hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    unified_msg = UnifiedMessage(
                        role="assistant",
                        content="",
                        tool_calls=[
                            ToolCall(
                                function=ToolCallFunction(
                                    name=fc.name,
                                    arguments=dict(fc.args) if fc.args else {},
                                )
                            )
                        ],
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
        response = await self._client.aio.models.embed_content(
            model=model,
            contents=prompt,
        )

        return UnifiedEmbeddingResponse(
            embedding=list(response.embeddings[0].values) if response.embeddings else [],
            model=model,
        )

    def update_config(self, config: "ModelConfig") -> None:
        """更新配置并重建客户端"""
        super().update_config(config)
        self._client = self._build_client()
        logger.info(f"GeminiProvider 配置已更新")

    # ==================== 转换工具方法 ====================

    @staticmethod
    def _convert_messages(messages: list[dict]) -> tuple[str, list]:
        """
        将 OpenAI 格式的消息转换为 Gemini 格式

        Gemini 使用 "user" 和 "model" 角色（不是 "assistant"）
        system 消息需要作为 system_instruction 单独传入
        """
        system_parts = []
        gemini_contents = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                system_parts.append(content)
            elif role == "assistant":
                gemini_contents.append({"role": "model", "parts": [{"text": content}]})
            elif role == "tool":
                # Gemini 的工具结果格式
                gemini_contents.append(
                    {"role": "user", "parts": [{"text": f"[工具结果] {content}"}]}
                )
            else:
                gemini_contents.append({"role": "user", "parts": [{"text": content}]})

        system_instruction = "\n\n".join(system_parts) if system_parts else ""

        # Gemini 要求交替的 user/model 消息，合并连续的同角色消息
        gemini_contents = GeminiProvider._merge_consecutive_roles(gemini_contents)

        return system_instruction, gemini_contents

    @staticmethod
    def _merge_consecutive_roles(contents: list) -> list:
        """合并连续相同角色的消息"""
        if not contents:
            return contents

        merged = [contents[0]]
        for msg in contents[1:]:
            if msg["role"] == merged[-1]["role"]:
                # 合并 parts
                merged[-1]["parts"].extend(msg["parts"])
            else:
                merged.append(msg)
        return merged

    def _convert_response(self, response, model: str) -> UnifiedResponse:
        """将 Gemini GenerateContentResponse 转换为 UnifiedResponse"""
        if not response.candidates:
            return UnifiedResponse(model=model)

        candidate = response.candidates[0]
        if not candidate.content or not candidate.content.parts:
            return UnifiedResponse(model=model)

        content_parts = []
        tool_calls = []

        for part in candidate.content.parts:
            if hasattr(part, "text") and part.text:
                content_parts.append(part.text)
            elif hasattr(part, "function_call") and part.function_call:
                fc = part.function_call
                tool_calls.append(
                    ToolCall(
                        function=ToolCallFunction(
                            name=fc.name,
                            arguments=dict(fc.args) if fc.args else {},
                        )
                    )
                )

        return UnifiedResponse(
            message=UnifiedMessage(
                role="assistant",
                content="".join(content_parts),
                tool_calls=tool_calls if tool_calls else None,
            ),
            model=model,
            done=True,
        )

    @staticmethod
    def _convert_tools_to_gemini(tools: list[dict]) -> list:
        """
        将 Ollama/OpenAI 格式的工具定义转换为 Gemini 格式

        Gemini 使用 function_declarations
        """
        try:
            from google.genai import types as genai_types
        except ImportError:
            return []

        declarations = []
        for tool in tools:
            if "function" in tool:
                func = tool["function"]
                declarations.append(
                    genai_types.FunctionDeclaration(
                        name=func.get("name", ""),
                        description=func.get("description", ""),
                        parameters=func.get("parameters"),
                    )
                )

        if declarations:
            return [genai_types.Tool(function_declarations=declarations)]
        return []
