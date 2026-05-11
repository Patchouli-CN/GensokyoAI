"""Provider 工厂 + 注册表"""

# GensokyoAI/core/agent/providers/__init__.py

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ....utils.logger import logger
from ..types import ProviderCapability
from .base import BaseProvider

if TYPE_CHECKING:
    from ...config import ModelConfig


@dataclass(frozen=True)
class ProviderDefinition:
    """Provider 控制面定义。

    该结构集中描述 Provider 的稳定元信息、默认配置、能力与外部模型注册表映射。
    ProviderFactory 仍只负责创建 BaseProvider 实例；具体请求行为继续由各 Provider 类实现。
    """

    id: str
    name: str
    protocol: str
    provider_class: type[BaseProvider]
    default_base_url: str | None = None
    default_api_path: str | None = None
    default_headers: dict[str, str] = field(default_factory=dict)
    capabilities: frozenset[str] = field(default_factory=frozenset)
    dependency_key: str | None = None
    model_registry_id: str | None = None
    builtin: bool = True

    def __post_init__(self) -> None:
        """标准化 Provider 控制面能力声明，避免注册表与实例能力使用不同命名。"""
        object.__setattr__(
            self, "capabilities", frozenset(ProviderCapability.normalize(self.capabilities))
        )


class ProviderFactory:
    """
    Provider 工厂 - 根据配置创建对应的 LLM Provider

    支持：
    - 内置 Provider 自动注册
    - 用户自定义 Provider 动态注册

    用法：
        # 使用内置 Provider
        provider = ProviderFactory.create(config)

        # 注册自定义 Provider
        ProviderFactory.register("my_provider", MyProvider)
        provider = ProviderFactory.create(config)  # config.provider = "my_provider"
    """

    _registry: dict[str, ProviderDefinition] = {}
    _builtin_provider_ids: set[str] = set()
    _initialized: bool = False

    @classmethod
    def _ensure_builtins(cls) -> None:
        """延迟注册内置 Provider（避免循环导入）"""
        if cls._initialized:
            return

        cls._initialized = True

        definitions = cls._build_builtin_definitions()
        cls._validate_unique_definition_ids(definitions)
        for definition in definitions:
            cls._register_definition(definition)
            cls._builtin_provider_ids.add(definition.id)

    @staticmethod
    def _build_builtin_definitions() -> list[ProviderDefinition]:
        """构建内置 Provider 定义表。"""
        definitions: list[ProviderDefinition] = []

        # Ollama - 始终注册
        from .ollama_provider import OllamaProvider

        definitions.append(
            ProviderDefinition(
                id="ollama",
                name="Ollama",
                protocol="ollama",
                provider_class=OllamaProvider,
                default_base_url=None,
                default_api_path=None,
                capabilities=frozenset(
                    {
                        ProviderCapability.CHAT,
                        ProviderCapability.STREAM,
                        ProviderCapability.TOOLS,
                        ProviderCapability.EMBEDDINGS,
                        ProviderCapability.CUSTOM_ENDPOINT,
                    }
                ),
                dependency_key="ollama",
                model_registry_id="ollama",
            )
        )

        # OpenAI Chat Completions - 尝试注册
        try:
            from .openai_provider import OpenAIProvider

            definitions.append(
                ProviderDefinition(
                    id="openai",
                    name="OpenAI Compatible",
                    protocol="openai_chat_completions",
                    provider_class=OpenAIProvider,
                    default_base_url=None,
                    default_api_path="/chat/completions",
                    capabilities=frozenset(
                        {
                            ProviderCapability.CHAT,
                            ProviderCapability.STREAM,
                            ProviderCapability.TOOLS,
                            ProviderCapability.EMBEDDINGS,
                            ProviderCapability.CUSTOM_ENDPOINT,
                        }
                    ),
                    dependency_key="openai",
                    model_registry_id="openai",
                )
            )
        except ImportError:
            pass

        # OpenRouter - OpenAI 兼容协议的一等适配
        try:
            from .openrouter_provider import OpenRouterProvider

            definitions.append(
                ProviderDefinition(
                    id="openrouter",
                    name="OpenRouter",
                    protocol="openai_chat_completions",
                    provider_class=OpenRouterProvider,
                    default_base_url=OpenRouterProvider.DEFAULT_BASE_URL,
                    default_api_path="/chat/completions",
                    default_headers=dict(OpenRouterProvider.DEFAULT_HEADERS),
                    capabilities=frozenset(
                        {
                            ProviderCapability.CHAT,
                            ProviderCapability.STREAM,
                            ProviderCapability.TOOLS,
                            ProviderCapability.CUSTOM_ENDPOINT,
                        }
                    ),
                    dependency_key="openai",
                    model_registry_id="openrouter",
                )
            )
        except ImportError:
            pass

        # DeepSeek - OpenAI 兼容但有独立 thinking/reasoning_content 语义
        try:
            from .deepseek_provider import DeepSeekProvider

            definitions.append(
                ProviderDefinition(
                    id="deepseek",
                    name="DeepSeek",
                    protocol="openai_chat_completions",
                    provider_class=DeepSeekProvider,
                    default_base_url=DeepSeekProvider.DEFAULT_BASE_URL,
                    default_api_path="/chat/completions",
                    capabilities=frozenset(
                        {
                            ProviderCapability.CHAT,
                            ProviderCapability.STREAM,
                            ProviderCapability.TOOLS,
                            ProviderCapability.CUSTOM_ENDPOINT,
                            ProviderCapability.REASONING,
                        }
                    ),
                    dependency_key="openai",
                    model_registry_id="deepseek",
                )
            )
        except ImportError:
            pass

        # OpenAI Responses API - 尝试注册
        try:
            from .openai_responses_provider import OpenAIResponsesProvider

            definitions.append(
                ProviderDefinition(
                    id="openai_responses",
                    name="OpenAI Responses",
                    protocol="openai_responses",
                    provider_class=OpenAIResponsesProvider,
                    default_base_url=None,
                    default_api_path="/responses",
                    capabilities=frozenset(
                        {
                            ProviderCapability.CHAT,
                            ProviderCapability.STREAM,
                            ProviderCapability.TOOLS,
                            ProviderCapability.EMBEDDINGS,
                            ProviderCapability.VISION,
                            ProviderCapability.REASONING,
                            ProviderCapability.RESPONSES_API,
                            ProviderCapability.CUSTOM_ENDPOINT,
                            ProviderCapability.WEB_SEARCH,
                        }
                    ),
                    dependency_key="openai",
                    model_registry_id="openai",
                )
            )
        except ImportError:
            pass

        # Claude - 尝试注册
        try:
            from .claude_provider import ClaudeProvider

            definitions.append(
                ProviderDefinition(
                    id="claude",
                    name="Claude",
                    protocol="anthropic_messages",
                    provider_class=ClaudeProvider,
                    default_base_url=None,
                    default_api_path=None,
                    capabilities=frozenset(
                        {
                            ProviderCapability.CHAT,
                            ProviderCapability.STREAM,
                            ProviderCapability.TOOLS,
                            ProviderCapability.VISION,
                            ProviderCapability.REASONING,
                        }
                    ),
                    dependency_key="claude",
                    model_registry_id="anthropic",
                )
            )
        except ImportError:
            pass

        # Gemini - 尝试注册
        try:
            from .gemini_provider import GeminiProvider

            definitions.append(
                ProviderDefinition(
                    id="gemini",
                    name="Gemini",
                    protocol="google_genai",
                    provider_class=GeminiProvider,
                    default_base_url=None,
                    default_api_path=None,
                    capabilities=frozenset(
                        {
                            ProviderCapability.CHAT,
                            ProviderCapability.STREAM,
                            ProviderCapability.TOOLS,
                            ProviderCapability.EMBEDDINGS,
                            ProviderCapability.VISION,
                            ProviderCapability.REASONING,
                            ProviderCapability.WEB_SEARCH,
                        }
                    ),
                    dependency_key="gemini",
                    model_registry_id="google",
                )
            )
        except ImportError:
            pass

        return definitions

    @staticmethod
    def _validate_unique_definition_ids(definitions: list[ProviderDefinition]) -> None:
        """校验一批定义内的 Provider ID 唯一。"""
        seen: set[str] = set()
        duplicates: set[str] = set()
        for definition in definitions:
            if definition.id in seen:
                duplicates.add(definition.id)
            seen.add(definition.id)
        if duplicates:
            duplicate_text = ", ".join(sorted(duplicates))
            raise ValueError(f"内置 ProviderDefinition ID 重复: {duplicate_text}")

    @classmethod
    def _register_definition(cls, definition: ProviderDefinition) -> None:
        """注册 ProviderDefinition。"""
        if not issubclass(definition.provider_class, BaseProvider):
            raise TypeError(f"{definition.provider_class.__name__} 必须继承 BaseProvider")
        if not definition.id:
            raise ValueError("ProviderDefinition.id 不能为空")
        if definition.id in cls._registry:
            raise ValueError(f"Provider ID 已注册: {definition.id}")
        unknown = ProviderCapability.unknown(definition.capabilities)
        if unknown:
            unknown_text = ", ".join(sorted(unknown))
            raise ValueError(f"ProviderDefinition 包含未知能力: {definition.id} -> {unknown_text}")

        cls._registry[definition.id] = definition

    @classmethod
    def register(cls, name: str, provider_cls: type[BaseProvider]) -> None:
        """
        注册自定义 Provider

        Args:
            name: Provider 名称（用于配置文件中的 provider 字段）
            provider_cls: Provider 类（必须继承 BaseProvider）

        Example:
            ProviderFactory.register("my_llm", MyLLMProvider)
        """
        cls._ensure_builtins()

        if not issubclass(provider_cls, BaseProvider):
            raise TypeError(f"{provider_cls.__name__} 必须继承 BaseProvider")
        if name in cls._builtin_provider_ids:
            raise ValueError(f"自定义 Provider 不能覆盖内置 Provider ID: {name}")
        if name in cls._registry:
            raise ValueError(f"Provider ID 已注册: {name}")

        definition = ProviderDefinition(
            id=name,
            name=name,
            protocol="custom",
            provider_class=provider_cls,
            capabilities=frozenset(),
            dependency_key=None,
            model_registry_id=None,
            builtin=False,
        )
        cls._register_definition(definition)
        logger.info(f"注册 Provider: {name} -> {provider_cls.__name__}")

    @classmethod
    def create(cls, config: ModelConfig, **kwargs) -> BaseProvider:
        """
        根据配置创建 Provider 实例

        Args:
            config: 模型配置
            **kwargs: 额外参数传递给 Provider 构造函数

        Returns:
            BaseProvider: Provider 实例

        Raises:
            ValueError: 未知的 Provider 类型
            ImportError: 对应 SDK 未安装
        """
        cls._ensure_builtins()

        provider_name = config.provider
        definition = cls._registry.get(provider_name)

        if not definition:
            available = ", ".join(cls._registry.keys())
            raise ValueError(
                f"未知的 Provider: '{provider_name}'\n"
                f"可用的 Provider: {available}\n"
                f"请检查配置中的 model.provider 字段"
            )

        provider_cls = definition.provider_class
        logger.info(f"创建 Provider: {provider_name} -> {provider_cls.__name__}")
        return provider_cls(config, **kwargs)

    @classmethod
    def get_provider_definition(cls, name: str) -> ProviderDefinition | None:
        """获取指定 ProviderDefinition。"""
        cls._ensure_builtins()
        return cls._registry.get(name)

    @classmethod
    def get_all_provider_definitions(cls) -> dict[str, ProviderDefinition]:
        """获取所有 ProviderDefinition 的只读快照。"""
        cls._ensure_builtins()
        return dict(cls._registry)

    @classmethod
    def available_providers(cls) -> list[str]:
        """获取所有可用的 Provider 名称"""
        cls._ensure_builtins()
        return list(cls._registry.keys())


__all__ = ["BaseProvider", "ProviderDefinition", "ProviderFactory"]
