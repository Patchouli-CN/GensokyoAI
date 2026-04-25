"""统一类型系统 - 消除 ollama 类型耦合"""

# GensokyoAI/core/agent/types.py

import msgspec
import msgspec.json
from typing import Sequence
from msgspec import Struct, field


class ToolCallFunction(Struct):
    """工具调用函数"""

    name: str = ""
    arguments: dict = field(default_factory=dict)
    provider: str = "openai"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "arguments": (
                msgspec.json.encode(self.arguments).decode() 
                if self.provider in ("openai", "openai_responses", "deepseek")
                else self.arguments
            ),
        }


class ToolCall(Struct):
    """工具调用"""

    id: str = ""
    type: str = "function"
    provider: str = "openai"
    function: ToolCallFunction = field(default_factory=ToolCallFunction)

    def to_dict(self) -> dict:
        self.function.provider = self.provider
        return {"id": self.id, "type": self.type, "function": self.function.to_dict()}


class UnifiedMessage(Struct):
    """
    统一消息类型 - 替代 ollama.Message

    所有 Provider 返回的消息都转换为此类型
    """

    role: str = "assistant"
    content: str = ""
    tool_calls: list[ToolCall] | None = None
    reasoning_content: str | None = None


class UnifiedResponse(Struct):
    """
    统一响应类型 - 替代 ollama.ChatResponse

    所有 Provider 的非流式响应都转换为此类型
    """

    message: UnifiedMessage = field(default_factory=UnifiedMessage)
    model: str = ""
    done: bool = True
    thinking: str | None = None


class UnifiedEmbeddingResponse(Struct):
    """
    统一 Embedding 响应类型 - 替代 ollama.EmbeddingsResponse
    """

    embedding: Sequence[float] = field(default_factory=list)
    model: str = ""


class StreamChunk(Struct):
    """
    流式响应块

    替代原来在 model_client.py 中定义的 StreamChunk
    """

    content: str = ""
    reasoning_content: str | None = None
    is_tool_call: bool = False
    tool_info: dict | None = None
