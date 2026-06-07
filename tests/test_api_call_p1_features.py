# pyright: reportAttributeAccessIssue=false, reportOptionalMemberAccess=false, reportOptionalSubscript=false, reportArgumentType=false

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from GensokyoAI.core.agent.model_client import ModelClient
from GensokyoAI.core.agent.providers import ProviderFactory
from GensokyoAI.core.agent.providers.base import BaseProvider
from GensokyoAI.core.agent.providers.claude_provider import ClaudeProvider
from GensokyoAI.core.agent.providers.deepseek_provider import DeepSeekProvider
from GensokyoAI.core.agent.providers.gemini_provider import GeminiProvider
from GensokyoAI.core.agent.providers.ollama_provider import OllamaProvider
from GensokyoAI.core.agent.providers.openai_provider import OpenAIProvider
from GensokyoAI.core.agent.providers.openai_responses_provider import OpenAIResponsesProvider
from GensokyoAI.core.agent.providers.openrouter_provider import OpenRouterProvider
from GensokyoAI.core.agent.types import (
    GeneratedImage,
    ImageGenerationRequest,
    ImageGenerationResult,
    ImageInput,
    MessageContentPart,
    ModelCallTiming,
    ModelInfo,
    ProviderCapability,
    StreamChunk,
    UnifiedEmbeddingResponse,
    UnifiedMessage,
    UnifiedResponse,
)
from GensokyoAI.core.config import ConfigLoader, EmbeddingConfig, ModelConfig, ToolConfig
from GensokyoAI.core.events import SystemEvent


class _EmbeddingsProvider(BaseProvider):
    @property
    def capabilities(self) -> set[str]:
        return super().capabilities | {ProviderCapability.EMBEDDINGS}

    async def chat(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        raise NotImplementedError

    async def chat_stream(
        self, model: str, messages: list[dict], tools=None, options=None, **kwargs
    ):
        if False:
            yield None


class _NoEmbeddingsProvider(BaseProvider):
    async def chat(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        raise NotImplementedError

    async def chat_stream(
        self, model: str, messages: list[dict], tools=None, options=None, **kwargs
    ):
        if False:
            yield None


class _ImageProvider(BaseProvider):
    @property
    def capabilities(self) -> set[str]:
        return super().capabilities | {ProviderCapability.IMAGE_GENERATION}

    async def chat(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        raise NotImplementedError

    async def chat_stream(
        self, model: str, messages: list[dict], tools=None, options=None, **kwargs
    ):
        if False:
            yield None

    async def image_generation(self, request: ImageGenerationRequest, **kwargs):
        return ImageGenerationResult(
            images=[
                GeneratedImage(url="https://example.test/image.png", revised_prompt=request.prompt)
            ],
            model=request.model or "image-model",
        )


class _ImageUnsupportedProvider(_NoEmbeddingsProvider):
    pass


class _TimingProvider(BaseProvider):
    async def chat(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        return UnifiedResponse(
            message=UnifiedMessage(content="answer", reasoning_content="think"),
            model=model,
            done=True,
        )

    async def chat_stream(
        self, model: str, messages: list[dict], tools=None, options=None, **kwargs
    ):
        yield StreamChunk(type="reasoning", reasoning_content="思考")
        yield StreamChunk(content="回答")
        yield StreamChunk(type="finish", finish_reason="stop", usage={"total_tokens": 3})

    async def embeddings(self, model: str, prompt: str, **kwargs):
        return UnifiedEmbeddingResponse(embedding=[0.1, 0.2, 0.3], model=model)


class _FailOnceStreamProvider(BaseProvider):
    calls = 0

    async def chat(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        raise NotImplementedError

    async def chat_stream(
        self, model: str, messages: list[dict], tools=None, options=None, **kwargs
    ):
        self.__class__.calls += 1
        if self.__class__.calls == 1:
            error = RuntimeError("temporary")
            error.status_code = 502
            raise error
        yield StreamChunk(content="ok")


class _FakeModelsClient:
    async def list(self):
        return SimpleNamespace(
            data=[
                SimpleNamespace(
                    id="openrouter/test-reasoning",
                    name="OpenRouter Test Reasoning",
                    owned_by="tester",
                    context_length=128000,
                    input_modalities=["text", "image"],
                    output_modalities=["text"],
                    supported_parameters=["tools", "response_format", "include_reasoning"],
                    supported_features=["web_search"],
                    pricing={"prompt": "0.000001", "internal_reasoning": "1"},
                    top_provider={"context_length": 128000, "max_completion_tokens": 8192},
                    per_request_limits={"prompt_tokens": 128000},
                )
            ]
        )


class _FakeOpenAIClient:
    def __init__(self):
        self.models = _FakeModelsClient()


class _SlowFirstChunkProvider(BaseProvider):
    async def chat(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        raise NotImplementedError

    async def chat_stream(
        self, model: str, messages: list[dict], tools=None, options=None, **kwargs
    ):
        await asyncio.sleep(0.05)
        yield StreamChunk(content="late")


class _CollectingEventBus:
    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)


class P1ApiCallFeatureTests(unittest.TestCase):
    def test_stream_chunk_new_fields_are_optional_and_settable(self):
        timing = ModelCallTiming(context="chat_stream", duration_ms=12.3)
        chunk = StreamChunk(
            type="finish",
            status="done",
            usage={"total_tokens": 3},
            finish_reason="stop",
            timing=timing,
        )
        self.assertEqual(chunk.type, "finish")
        self.assertEqual(chunk.status, "done")
        self.assertEqual(chunk.usage["total_tokens"], 3)
        self.assertEqual(chunk.finish_reason, "stop")
        self.assertEqual(chunk.timing.duration_ms, 12.3)

    def test_image_generation_facade_returns_unified_result(self):
        event_bus = _CollectingEventBus()
        client = ModelClient.__new__(ModelClient)
        client.config = ModelConfig(provider="test", name="image-model", retry_initial_delay=0)
        client._provider = _ImageProvider(client.config)
        client._event_bus = event_bus

        result = asyncio.run(client.generate_image("画一只猫", size="1024x1024"))

        self.assertEqual(result.images[0].url, "https://example.test/image.png")
        self.assertEqual(result.images[0].revised_prompt, "画一只猫")
        self.assertEqual(result.model, "image-model")
        self.assertIsNotNone(result.timing)
        self.assertEqual(result.timing.context, "image_generation")

    def test_image_generation_requires_capability(self):
        client = ModelClient.__new__(ModelClient)
        client.config = ModelConfig(provider="test", name="text-model")
        client._provider = _ImageUnsupportedProvider(client.config)
        client._event_bus = None

        with self.assertRaises(Exception) as ctx:
            asyncio.run(client.generate_image("画一只猫"))

        self.assertIn("不支持图片生成", str(ctx.exception))

    def test_openai_clean_messages_converts_unified_image_parts(self):
        cleaned = OpenAIProvider._clean_messages(
            [
                {
                    "role": "user",
                    "content": [
                        MessageContentPart(type="text", text="看图"),
                        MessageContentPart(
                            type="image",
                            image=ImageInput(data="ZmFrZQ==", mime_type="image/jpeg", detail="low"),
                        ),
                    ],
                    "reasoning_content": "remove me",
                }
            ]
        )

        self.assertNotIn("reasoning_content", cleaned[0])
        self.assertEqual(cleaned[0]["content"][0], {"type": "text", "text": "看图"})
        self.assertEqual(cleaned[0]["content"][1]["type"], "image_url")
        self.assertEqual(
            cleaned[0]["content"][1]["image_url"],
            {"url": "data:image/jpeg;base64,ZmFrZQ==", "detail": "low"},
        )

    def test_responses_converts_unified_image_parts(self):
        instructions, input_items = OpenAIResponsesProvider._convert_messages_to_input(
            [
                {"role": "system", "content": "sys"},
                {
                    "role": "user",
                    "content": [
                        MessageContentPart(type="text", text="描述"),
                        MessageContentPart(
                            type="image", image=ImageInput(url="https://example.test/a.png")
                        ),
                    ],
                },
            ]
        )

        self.assertEqual(instructions, "sys")
        self.assertEqual(input_items[0]["role"], "user")
        self.assertEqual(input_items[0]["content"][0], {"type": "input_text", "text": "描述"})
        self.assertEqual(
            input_items[0]["content"][1],
            {"type": "input_image", "image_url": "https://example.test/a.png"},
        )

    def test_gemini_converts_unified_image_parts(self):
        system_instruction, contents = GeminiProvider._convert_messages(
            [
                {"role": "system", "content": "sys"},
                {
                    "role": "user",
                    "content": [
                        MessageContentPart(type="text", text="描述"),
                        MessageContentPart(
                            type="image", image=ImageInput(data="ZmFrZQ==", mime_type="image/png")
                        ),
                    ],
                },
            ]
        )

        self.assertEqual(system_instruction, "sys")
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(contents[0]["parts"][0], {"text": "描述"})
        self.assertEqual(
            contents[0]["parts"][1],
            {"inline_data": {"mime_type": "image/png", "data": "ZmFrZQ=="}},
        )

    def test_claude_converts_unified_image_parts(self):
        system_prompt, messages = ClaudeProvider._convert_messages_to_claude(
            [
                {"role": "system", "content": "sys"},
                {
                    "role": "user",
                    "content": [
                        MessageContentPart(type="text", text="描述"),
                        MessageContentPart(
                            type="image", image=ImageInput(data="ZmFrZQ==", mime_type="image/png")
                        ),
                    ],
                },
            ]
        )

        self.assertEqual(system_prompt, "sys")
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[0]["content"][0], {"type": "text", "text": "描述"})
        self.assertEqual(
            messages[0]["content"][1],
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": "ZmFrZQ=="},
            },
        )

    def test_base_provider_capabilities_and_supports(self):
        provider = _NoEmbeddingsProvider(ModelConfig())
        self.assertTrue(provider.supports(ProviderCapability.CHAT))
        self.assertTrue(provider.supports(ProviderCapability.STREAM))
        self.assertFalse(provider.supports(ProviderCapability.EMBEDDINGS))

    def test_builtin_provider_capability_declarations(self):
        checks = [
            (OpenAIProvider, {ProviderCapability.EMBEDDINGS, ProviderCapability.CUSTOM_ENDPOINT}),
            (OpenRouterProvider, {ProviderCapability.TOOLS, ProviderCapability.CUSTOM_ENDPOINT}),
            (
                OpenAIResponsesProvider,
                {
                    ProviderCapability.RESPONSES_API,
                    ProviderCapability.REASONING,
                    ProviderCapability.WEB_SEARCH,
                },
            ),
            (DeepSeekProvider, {ProviderCapability.REASONING}),
            (OllamaProvider, {ProviderCapability.EMBEDDINGS}),
            (
                GeminiProvider,
                {
                    ProviderCapability.VISION,
                    ProviderCapability.EMBEDDINGS,
                    ProviderCapability.WEB_SEARCH,
                    ProviderCapability.STRUCTURED_OUTPUT,
                },
            ),
            (ClaudeProvider, {ProviderCapability.REASONING, ProviderCapability.VISION}),
        ]
        for provider_cls, expected in checks:
            provider = provider_cls.__new__(provider_cls)
            BaseProvider.__init__(provider, ModelConfig(provider="test", name="test"))
            self.assertTrue(expected.issubset(provider.capabilities), provider_cls.__name__)

    def test_openai_official_endpoint_declares_image_capabilities(self):
        provider = OpenAIProvider.__new__(OpenAIProvider)
        BaseProvider.__init__(provider, ModelConfig(provider="openai", name="gpt-4.1"))
        provider._endpoint = SimpleNamespace(api_host="https://api.openai.com/v1")

        self.assertIn(ProviderCapability.IMAGE, provider.capabilities)
        self.assertIn(ProviderCapability.IMAGE_GENERATION, provider.capabilities)

    def test_openai_compatible_endpoint_does_not_default_to_image_capabilities(self):
        provider = OpenAIProvider.__new__(OpenAIProvider)
        BaseProvider.__init__(
            provider,
            ModelConfig(provider="openai", name="test", base_url="https://compatible.example/v1"),
        )
        provider._endpoint = SimpleNamespace(api_host="https://compatible.example/v1")

        self.assertNotIn(ProviderCapability.IMAGE, provider.capabilities)
        self.assertNotIn(ProviderCapability.IMAGE_GENERATION, provider.capabilities)

    def test_openai_compatible_endpoint_can_add_image_capability_by_config(self):
        provider = OpenAIProvider.__new__(OpenAIProvider)
        BaseProvider.__init__(
            provider,
            ModelConfig(
                provider="openai",
                name="test",
                base_url="https://compatible.example/v1",
                model_capabilities_add=[ProviderCapability.IMAGE_GENERATION],
            ),
        )
        provider._endpoint = SimpleNamespace(api_host="https://compatible.example/v1")

        self.assertIn(ProviderCapability.IMAGE_GENERATION, provider.capabilities)

    def test_config_loader_merge_model_respects_explicit_default_values(self):
        loader = ConfigLoader()
        base = loader._dict_to_config(
            {
                "model": {
                    "provider": "openai",
                    "name": "gpt-4.1",
                    "temperature": 1.2,
                    "max_tokens": 4096,
                    "timeout": 120,
                    "retry_max_attempts": 5,
                }
            }
        )
        override = loader._dict_to_config(
            {
                "model": {
                    "temperature": 0.7,
                    "max_tokens": 2048,
                    "timeout": 60,
                    "retry_max_attempts": 3,
                }
            }
        )

        merged = loader._merge(base, override)

        self.assertEqual(merged.model.provider, "openai")
        self.assertEqual(merged.model.name, "gpt-4.1")
        self.assertEqual(merged.model.temperature, 0.7)
        self.assertEqual(merged.model.max_tokens, 2048)
        self.assertEqual(merged.model.timeout, 60)
        self.assertEqual(merged.model.retry_max_attempts, 3)

    def test_config_loader_load_user_model_default_values_override_default_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            user_config = Path(tmp) / "config.yaml"
            user_config.write_text(
                "model:\n"
                "  temperature: 0.7\n"
                "  max_tokens: 2048\n"
                "  timeout: 60\n"
                "  retry_max_attempts: 3\n",
                encoding="utf-8",
            )

            config = ConfigLoader().load(user_config)

        self.assertEqual(config.model.temperature, 0.7)
        self.assertEqual(config.model.max_tokens, 2048)
        self.assertEqual(config.model.timeout, 60)
        self.assertEqual(config.model.retry_max_attempts, 3)

    def test_config_loader_merge_non_model_sections_respects_explicit_default_values(self):
        loader = ConfigLoader()
        base = loader._dict_to_config(
            {
                "debug_silent_output": True,
                "event_trace_enabled": True,
                "embedding": {
                    "provider": "openai",
                    "name": "embed-large",
                    "dimensions": 1024,
                    "use_proxy": True,
                },
                "memory": {
                    "working_max_turns": 99,
                    "semantic_enabled": False,
                    "auto_memory_enabled": False,
                    "topic_generation": {"name_max_length": 20, "summary_max_length": 200},
                },
                "tool": {
                    "enabled": False,
                    "builtin_tools": ["time"],
                    "web_search": {
                        "enabled": True,
                        "provider": "api",
                        "max_results": 20,
                        "trigger_strategy": "auto",
                        "api": {"method": "GET", "results_path": "items"},
                    },
                },
                "session": {"auto_save": False, "max_sessions": 200},
                "think_engine": {
                    "enabled": False,
                    "think_interval_minutes": 10,
                    "think_max_tokens": 400,
                },
            }
        )
        override = loader._dict_to_config(
            {
                "debug_silent_output": False,
                "event_trace_enabled": False,
                "embedding": {
                    "provider": None,
                    "name": None,
                    "dimensions": None,
                    "use_proxy": None,
                },
                "memory": {
                    "working_max_turns": 20,
                    "semantic_enabled": True,
                    "auto_memory_enabled": True,
                    "topic_generation": {"name_max_length": 10, "summary_max_length": 100},
                },
                "tool": {
                    "enabled": True,
                    "builtin_tools": ["time", "moon", "memory", "system"],
                    "web_search": {
                        "enabled": False,
                        "provider": "bing",
                        "max_results": 10,
                        "trigger_strategy": "explicit",
                        "api": {"method": "POST", "results_path": "results"},
                    },
                },
                "session": {"auto_save": True, "max_sessions": 100},
                "think_engine": {
                    "enabled": True,
                    "think_interval_minutes": 5,
                    "think_max_tokens": 200,
                },
            }
        )

        merged = loader._merge(base, override)

        self.assertFalse(merged.debug_silent_output)
        self.assertFalse(merged.event_trace_enabled)
        self.assertIsNone(merged.embedding.provider)
        self.assertIsNone(merged.embedding.name)
        self.assertIsNone(merged.embedding.dimensions)
        self.assertIsNone(merged.embedding.use_proxy)
        self.assertEqual(merged.memory.working_max_turns, 20)
        self.assertTrue(merged.memory.semantic_enabled)
        self.assertTrue(merged.memory.auto_memory_enabled)
        self.assertEqual(merged.memory.topic_generation.name_max_length, 10)
        self.assertEqual(merged.memory.topic_generation.summary_max_length, 100)
        self.assertTrue(merged.tool.enabled)
        self.assertEqual(merged.tool.builtin_tools, ["time", "moon", "memory", "system"])
        self.assertFalse(merged.tool.web_search.enabled)
        self.assertEqual(merged.tool.web_search.provider, "bing")
        self.assertEqual(merged.tool.web_search.max_results, 10)
        self.assertEqual(merged.tool.web_search.trigger_strategy, "explicit")
        self.assertEqual(merged.tool.web_search.api.method, "POST")
        self.assertEqual(merged.tool.web_search.api.results_path, "results")
        self.assertTrue(merged.session.auto_save)
        self.assertEqual(merged.session.max_sessions, 100)
        self.assertTrue(merged.think_engine.enabled)
        self.assertEqual(merged.think_engine.think_interval_minutes, 5)
        self.assertEqual(merged.think_engine.think_max_tokens, 200)

    def test_tool_config_default_includes_event_trace_default(self):
        config = ConfigLoader()._dict_to_config({"tool": {}})

        self.assertIsInstance(config.tool, ToolConfig)
        self.assertFalse(config.event_trace_enabled)

    def test_model_client_supports_embeddings_uses_capability(self):
        client = ModelClient.__new__(ModelClient)
        client.config = ModelConfig()
        client._embedding_config = EmbeddingConfig(name="embed-model")
        client._embedding_provider = _EmbeddingsProvider(ModelConfig())
        client._get_embedding_provider = lambda: (
            client._embedding_provider,
            ModelConfig(name="embed-model"),
        )
        self.assertTrue(client.supports_embeddings)

    def test_openai_extra_headers_passed_to_sdk(self):
        captured = {}

        class FakeAsyncOpenAI:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        with patch.dict("sys.modules", {"openai": SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI)}):
            provider = OpenAIProvider(
                ModelConfig(
                    provider="openai",
                    name="test",
                    api_key="sk-test",
                    extra_headers={"X-Test": "1"},
                )
            )

        self.assertEqual(captured["default_headers"], {"X-Test": "1"})
        self.assertIn("base_url", captured)
        self.assertEqual(provider.config.extra_headers["X-Test"], "1")

    def test_openai_list_models_maps_metadata_and_capabilities(self):
        provider = OpenAIProvider.__new__(OpenAIProvider)
        BaseProvider.__init__(provider, ModelConfig(provider="openai", name="fallback"))
        provider._client = _FakeOpenAIClient()

        models = asyncio.run(provider.list_models())

        self.assertEqual(len(models), 1)
        self.assertIsInstance(models[0], ModelInfo)
        self.assertEqual(models[0].id, "openrouter/test-reasoning")
        self.assertEqual(models[0].context_window, 128000)
        self.assertIn(ProviderCapability.VISION, models[0].capabilities)
        self.assertIn(ProviderCapability.REASONING, models[0].capabilities)
        self.assertIn(ProviderCapability.WEB_SEARCH, models[0].capabilities)

    def test_openrouter_registered_in_provider_factory(self):
        captured = {}

        class FakeAsyncOpenAI:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        with patch.dict("sys.modules", {"openai": SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI)}):
            provider = ProviderFactory.create(
                ModelConfig(provider="openrouter", name="openai/gpt-4o", api_key="sk-or-test")
            )

        self.assertIsInstance(provider, OpenRouterProvider)
        self.assertIn("openrouter", ProviderFactory.available_providers())
        self.assertEqual(captured["api_key"], "sk-or-test")

    def test_openrouter_default_headers_can_be_overridden(self):
        captured = {}

        class FakeAsyncOpenAI:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        with patch.dict("sys.modules", {"openai": SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI)}):
            provider = OpenRouterProvider(
                ModelConfig(
                    provider="openrouter",
                    name="openai/gpt-4o",
                    api_key="sk-or-test",
                    extra_headers={"HTTP-Referer": "https://example.test", "X-Custom": "1"},
                )
            )

        self.assertEqual(captured["base_url"], "https://openrouter.ai/api/v1")
        self.assertEqual(captured["default_headers"]["HTTP-Referer"], "https://example.test")
        self.assertEqual(captured["default_headers"]["X-Title"], "GensokyoAI")
        self.assertEqual(captured["default_headers"]["X-Custom"], "1")
        self.assertEqual(provider.config.base_url, "https://openrouter.ai/api/v1")

    def test_openrouter_list_models_keeps_metadata_and_infers_capabilities(self):
        provider = OpenRouterProvider.__new__(OpenRouterProvider)
        BaseProvider.__init__(provider, ModelConfig(provider="openrouter", name="fallback"))
        provider._client = _FakeOpenAIClient()

        models = asyncio.run(provider.list_models())

        self.assertEqual(len(models), 1)
        model = models[0]
        self.assertEqual(model.name, "OpenRouter Test Reasoning")
        self.assertEqual(model.metadata["provider"], "openrouter")
        self.assertEqual(model.metadata["top_provider"]["max_completion_tokens"], 8192)
        self.assertEqual(model.metadata["per_request_limits"]["prompt_tokens"], 128000)
        self.assertIn(ProviderCapability.TOOLS, model.capabilities)
        self.assertIn(ProviderCapability.VISION, model.capabilities)
        self.assertIn(ProviderCapability.REASONING, model.capabilities)
        self.assertIn(ProviderCapability.WEB_SEARCH, model.capabilities)
        self.assertIn(ProviderCapability.STRUCTURED_OUTPUT, model.capabilities)

    def test_model_capability_overrides_add_and_remove(self):
        provider = OpenAIProvider.__new__(OpenAIProvider)
        BaseProvider.__init__(
            provider,
            ModelConfig(
                provider="openai",
                name="fallback",
                model_capabilities_add=["custom_capability"],
                model_capabilities_remove=[ProviderCapability.WEB_SEARCH],
            ),
        )
        provider._client = _FakeOpenAIClient()

        models = asyncio.run(provider.list_models())

        self.assertIn("custom_capability", models[0].capabilities)
        self.assertNotIn(ProviderCapability.WEB_SEARCH, models[0].capabilities)

    def test_responses_fallback_model_includes_web_search(self):
        provider = OpenAIResponsesProvider.__new__(OpenAIResponsesProvider)
        BaseProvider.__init__(provider, ModelConfig(provider="openai_responses", name="gpt-4.1"))
        provider._client = SimpleNamespace(models=SimpleNamespace(list=lambda: None))

        async def fail_list():
            raise RuntimeError("offline")

        provider._client.models.list = fail_list
        models = asyncio.run(provider.list_models())

        self.assertIn(ProviderCapability.WEB_SEARCH, models[0].capabilities)

    def test_gemini_model_metadata_can_infer_web_search(self):
        provider = GeminiProvider.__new__(GeminiProvider)
        BaseProvider.__init__(provider, ModelConfig(provider="gemini", name="gemini-2.5-pro"))

        capabilities = provider._infer_model_capabilities(
            "models/gemini-2.5-pro",
            {"supported_features": ["google_search"]},
        )

        self.assertIn(ProviderCapability.WEB_SEARCH, capabilities)

    def test_stream_retry_yields_status_chunk(self):
        _FailOnceStreamProvider.calls = 0
        client = ModelClient.__new__(ModelClient)
        client.config = ModelConfig(
            provider="test",
            name="test",
            retry_max_attempts=2,
            retry_initial_delay=0,
        )
        client._provider = _FailOnceStreamProvider(client.config)
        client._event_bus = None

        async def collect():
            return [
                chunk async for chunk in client.chat_stream([{"role": "user", "content": "hi"}])
            ]

        chunks = asyncio.run(collect())
        self.assertEqual(chunks[0].type, "status")
        self.assertEqual(chunks[0].status, "retrying")
        self.assertEqual(chunks[1].content, "ok")

    def test_chat_publishes_timing_event(self):
        event_bus = _CollectingEventBus()
        client = ModelClient.__new__(ModelClient)
        client.config = ModelConfig(provider="test", name="timing-model", retry_initial_delay=0)
        client._provider = _TimingProvider(client.config)
        client._event_bus = event_bus

        response = asyncio.run(client.chat([{"role": "user", "content": "hi"}]))

        self.assertEqual(response.message.content, "answer")
        timing_events = [e for e in event_bus.events if e.type == SystemEvent.MODEL_CALL_TIMING]
        self.assertEqual(len(timing_events), 1)
        data = timing_events[0].data
        self.assertEqual(data["context"], "chat")
        self.assertEqual(data["provider"], "test")
        self.assertEqual(data["model"], "timing-model")
        self.assertEqual(data["content_char_count"], 6)
        self.assertEqual(data["reasoning_char_count"], 5)
        self.assertIsNotNone(data["duration_ms"])

    def test_stream_timing_counts_reasoning_and_finish_chunk(self):
        event_bus = _CollectingEventBus()
        client = ModelClient.__new__(ModelClient)
        client.config = ModelConfig(provider="test", name="timing-model", retry_initial_delay=0)
        client._provider = _TimingProvider(client.config)
        client._event_bus = event_bus

        async def collect():
            return [
                chunk async for chunk in client.chat_stream([{"role": "user", "content": "hi"}])
            ]

        chunks = asyncio.run(collect())
        finish = chunks[-1]
        self.assertEqual(finish.type, "finish")
        self.assertIsNotNone(finish.timing)
        self.assertEqual(finish.timing.reasoning_chunk_count, 1)
        self.assertEqual(finish.timing.reasoning_char_count, 2)
        self.assertEqual(finish.timing.content_chunk_count, 1)
        self.assertEqual(finish.timing.content_char_count, 2)
        self.assertEqual(finish.timing.finish_reason, "stop")
        self.assertEqual(finish.timing.usage["total_tokens"], 3)
        self.assertIsNotNone(finish.timing.first_chunk_ms)
        self.assertIsNotNone(finish.timing.first_token_ms)
        self.assertIsNotNone(finish.timing.first_reasoning_ms)

        timing_events = [e for e in event_bus.events if e.type == SystemEvent.MODEL_CALL_TIMING]
        self.assertEqual(len(timing_events), 1)
        self.assertEqual(timing_events[0].data["context"], "chat_stream")

    def test_embeddings_publishes_timing_event(self):
        event_bus = _CollectingEventBus()
        client = ModelClient.__new__(ModelClient)
        client.config = ModelConfig(provider="test", name="chat-model", retry_initial_delay=0)
        client._embedding_config = EmbeddingConfig(provider="test", name="embed-model")
        client._embedding_provider = _TimingProvider(
            ModelConfig(provider="test", name="embed-model")
        )
        client._get_embedding_provider = lambda: (
            client._embedding_provider,
            client._embedding_provider.config,
        )
        client._event_bus = event_bus

        response = asyncio.run(client.embeddings("hello"))

        self.assertEqual(len(response.embedding), 3)
        timing_events = [e for e in event_bus.events if e.type == SystemEvent.MODEL_CALL_TIMING]
        self.assertEqual(len(timing_events), 1)
        data = timing_events[0].data
        self.assertEqual(data["context"], "embeddings")
        self.assertEqual(data["model"], "embed-model")
        self.assertEqual(data["timing"].prompt_length, 5)
        self.assertEqual(data["timing"].embedding_dimension, 3)

    def test_stream_timeout_publishes_structured_event(self):
        event_bus = _CollectingEventBus()
        client = ModelClient.__new__(ModelClient)
        client.config = ModelConfig(
            provider="test", name="test", timeout=0.01, retry_max_attempts=1
        )
        client._provider = _SlowFirstChunkProvider(client.config)
        client._event_bus = event_bus

        async def collect():
            return [
                chunk async for chunk in client.chat_stream([{"role": "user", "content": "hi"}])
            ]

        with self.assertRaises(TimeoutError):
            asyncio.run(collect())

        self.assertTrue(event_bus.events)
        data = event_bus.events[-1].data
        self.assertEqual(data["context"], "chat_stream")
        self.assertEqual(data["timeout"], 0.01)
        self.assertEqual(data["message_count"], 1)
        self.assertEqual(data["provider"], "test")
        self.assertEqual(data["model"], "test")

    def test_claude_chat_converts_response_format_to_output_config(self):
        captured = {}

        class _FakeMessages:
            async def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    content=[SimpleNamespace(type="text", text='{"ok": true}')],
                    model="test",
                )

        provider = ClaudeProvider.__new__(ClaudeProvider)
        BaseProvider.__init__(provider, ModelConfig(provider="claude", name="test"))
        provider._client = SimpleNamespace(messages=_FakeMessages())
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}

        asyncio.run(
            provider.chat(
                "test",
                [{"role": "user", "content": "hi"}],
                options={
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "test_schema",
                            "strict": True,
                            "schema": schema,
                        },
                    }
                },
            )
        )

        self.assertEqual(
            captured["output_config"],
            {"format": {"type": "json_schema", "schema": schema}},
        )

    def test_claude_declares_structured_output_capability(self):
        provider = ClaudeProvider.__new__(ClaudeProvider)
        BaseProvider.__init__(provider, ModelConfig(provider="claude", name="claude-test"))

        self.assertTrue(provider.supports(ProviderCapability.STRUCTURED_OUTPUT))

    def test_claude_list_models_returns_configured_fallback(self):
        provider = ClaudeProvider.__new__(ClaudeProvider)
        BaseProvider.__init__(provider, ModelConfig(provider="claude", name="claude-test"))

        models = asyncio.run(provider.list_models())

        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].id, "claude-test")
        self.assertEqual(models[0].metadata, {"fallback": True})
        self.assertIn(ProviderCapability.REASONING, models[0].capabilities)

    def test_claude_stream_tool_call_preserves_raw_arguments_on_json_error(self):
        class _FakeClaudeStream:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def __aiter__(self):
                async def stream():
                    yield SimpleNamespace(
                        type="content_block_start",
                        index=0,
                        content_block=SimpleNamespace(
                            type="tool_use",
                            id="tool-1",
                            name="broken_tool",
                        ),
                    )
                    yield SimpleNamespace(
                        type="content_block_delta",
                        index=0,
                        delta=SimpleNamespace(type="input_json_delta", partial_json='{"bad"'),
                    )
                    yield SimpleNamespace(type="message_stop")

                return stream()

        class _FakeClaudeMessages:
            def stream(self, **kwargs):
                return _FakeClaudeStream()

        provider = ClaudeProvider.__new__(ClaudeProvider)
        BaseProvider.__init__(provider, ModelConfig(provider="claude", name="test"))
        provider._client = SimpleNamespace(messages=_FakeClaudeMessages())

        async def collect():
            return [
                chunk
                async for chunk in provider.chat_stream("test", [{"role": "user", "content": "hi"}])
            ]

        chunks = asyncio.run(collect())
        self.assertEqual(chunks[0].type, "tool_call")
        self.assertEqual(chunks[0].tool_info["raw_arguments"], {0: '{"bad"'})

    def test_openai_stream_tool_call_preserves_raw_arguments_on_json_error(self):
        class _FakeChatCompletions:
            async def create(self, **kwargs):
                async def stream():
                    delta = SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id="call-1",
                                function=SimpleNamespace(name="broken_tool", arguments='{"bad"'),
                            )
                        ],
                    )
                    yield SimpleNamespace(
                        choices=[SimpleNamespace(delta=delta, finish_reason="tool_calls")],
                        usage=None,
                    )

                return stream()

        provider = OpenAIProvider.__new__(OpenAIProvider)
        BaseProvider.__init__(provider, ModelConfig(provider="openai", name="test"))
        provider._client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeChatCompletions()))

        async def collect():
            return [
                chunk
                async for chunk in provider.chat_stream("test", [{"role": "user", "content": "hi"}])
            ]

        chunks = asyncio.run(collect())
        self.assertEqual(chunks[0].type, "tool_call")
        self.assertEqual(chunks[0].tool_info["raw_arguments"], {0: '{"bad"'})

    def test_responses_stream_failed_yields_error_then_raises(self):
        class _FakeResponses:
            async def create(self, **kwargs):
                async def stream():
                    yield SimpleNamespace(
                        type="response.failed",
                        response=SimpleNamespace(error=SimpleNamespace(message="boom")),
                    )

                return stream()

        provider = OpenAIResponsesProvider.__new__(OpenAIResponsesProvider)
        BaseProvider.__init__(provider, ModelConfig(provider="openai_responses", name="test"))
        provider._endpoint = SimpleNamespace(
            api_host="https://api.openai.com/v1", api_path="/responses"
        )
        provider._client = SimpleNamespace(responses=_FakeResponses())

        async def collect_until_error():
            chunks = []
            with self.assertRaises(Exception) as ctx:
                async for chunk in provider.chat_stream(
                    "test", [{"role": "user", "content": "hi"}]
                ):
                    chunks.append(chunk)
            return chunks, ctx.exception

        chunks, error = asyncio.run(collect_until_error())
        self.assertEqual(chunks[0].type, "error")
        self.assertEqual(chunks[0].error, "boom")
        self.assertIn("boom", str(error))

    def test_responses_stream_tool_call_preserves_raw_arguments_on_json_error(self):
        class _FakeResponses:
            async def create(self, **kwargs):
                async def stream():
                    yield SimpleNamespace(
                        type="response.output_item.added",
                        output_index=0,
                        item=SimpleNamespace(
                            type="function_call",
                            call_id="call-1",
                            id="call-1",
                            name="broken_tool",
                            arguments="",
                        ),
                    )
                    yield SimpleNamespace(
                        type="response.function_call_arguments.done",
                        output_index=0,
                        arguments='{"bad"',
                    )
                    yield SimpleNamespace(
                        type="response.completed",
                        response=SimpleNamespace(usage=None),
                    )

                return stream()

        provider = OpenAIResponsesProvider.__new__(OpenAIResponsesProvider)
        BaseProvider.__init__(provider, ModelConfig(provider="openai_responses", name="test"))
        provider._endpoint = SimpleNamespace(
            api_host="https://api.openai.com/v1", api_path="/responses"
        )
        provider._client = SimpleNamespace(responses=_FakeResponses())

        async def collect():
            return [
                chunk
                async for chunk in provider.chat_stream("test", [{"role": "user", "content": "hi"}])
            ]

        chunks = asyncio.run(collect())
        self.assertEqual(chunks[0].type, "tool_call")
        self.assertEqual(chunks[0].tool_info["raw_arguments"], {0: '{"bad"'})

    def test_model_client_build_options_web_search_default_off(self):
        client = ModelClient.__new__(ModelClient)
        client.config = ModelConfig()
        options = client._build_options()
        self.assertNotIn("web_search", options)

    def test_model_client_build_options_web_search_explicit(self):
        client = ModelClient.__new__(ModelClient)
        client.config = ModelConfig(
            web_search_enabled=True,
            web_search_strategy="explicit",
            web_search_context_size="low",
            web_search_user_location={"type": "approximate", "country": "CN"},
        )
        options = client._build_options()
        self.assertTrue(options["web_search"]["enabled"])
        self.assertEqual(options["web_search"]["strategy"], "explicit")
        self.assertEqual(options["web_search"]["context_size"], "low")

    def test_responses_injects_web_search_tool_when_enabled(self):
        provider = OpenAIResponsesProvider.__new__(OpenAIResponsesProvider)
        BaseProvider.__init__(provider, ModelConfig(provider="openai_responses", name="test"))
        tools = []
        provider._inject_web_search_tool(
            tools,
            {
                "web_search": {
                    "enabled": True,
                    "strategy": "explicit",
                    "context_size": "medium",
                    "user_location": {"type": "approximate", "country": "US"},
                }
            },
        )
        self.assertEqual(tools[0]["type"], "web_search_preview")
        self.assertEqual(tools[0]["search_context_size"], "medium")
        self.assertEqual(tools[0]["user_location"]["country"], "US")

    def test_responses_extracts_url_citation_references(self):
        provider = OpenAIResponsesProvider.__new__(OpenAIResponsesProvider)
        BaseProvider.__init__(provider, ModelConfig(provider="openai_responses", name="test"))
        response = SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="message",
                    content=[
                        SimpleNamespace(
                            type="output_text",
                            text="answer",
                            annotations=[
                                SimpleNamespace(
                                    type="url_citation",
                                    title="Example",
                                    url="https://example.test/a",
                                    snippet="snippet",
                                )
                            ],
                        )
                    ],
                )
            ],
            model="test",
        )
        unified = provider._convert_response(response)
        self.assertEqual(unified.web_search_references[0].title, "Example")
        self.assertEqual(unified.web_search_references[0].url, "https://example.test/a")
        self.assertEqual(unified.web_search_diagnostics.status, "completed")

    def test_gemini_converts_response_format(self):
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "test_schema",
                "strict": True,
                "schema": schema,
            },
        }

        converted = GeminiProvider._response_format_to_gemini(response_format)

        self.assertEqual(
            converted,
            {
                "text": {
                    "mime_type": "application/json",
                    "schema": schema,
                }
            },
        )

    def test_gemini_converts_json_object_response_format(self):
        converted = GeminiProvider._response_format_to_gemini({"type": "json_object"})

        self.assertEqual(converted, {"text": {"mime_type": "application/json"}})

    def test_gemini_injects_google_search_tool_when_enabled(self):
        provider = GeminiProvider.__new__(GeminiProvider)
        BaseProvider.__init__(provider, ModelConfig(provider="gemini", name="test"))

        class _Types:
            class GoogleSearch:
                pass

            class Tool:
                def __init__(self, **kwargs):
                    self.google_search = kwargs.get("google_search")

        tools = []
        provider._inject_google_search_tool(
            tools,
            {"web_search": {"enabled": True, "strategy": "explicit"}},
            _Types,
        )
        self.assertIsNotNone(tools[0].google_search)

    def test_gemini_extracts_grounding_references(self):
        provider = GeminiProvider.__new__(GeminiProvider)
        BaseProvider.__init__(provider, ModelConfig(provider="gemini", name="test"))
        response = SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    grounding_metadata=SimpleNamespace(
                        grounding_chunks=[
                            SimpleNamespace(
                                web=SimpleNamespace(
                                    uri="https://example.test/g", title="Gemini Ref"
                                )
                            )
                        ]
                    ),
                    content=SimpleNamespace(parts=[SimpleNamespace(text="answer")]),
                )
            ]
        )
        unified = provider._convert_response(response, "test")
        self.assertEqual(unified.web_search_references[0].title, "Gemini Ref")
        self.assertEqual(unified.web_search_references[0].source, "gemini_grounding")

    def test_config_loads_web_search_fields_from_yaml(self):
        data = yaml.safe_load(
            """
            model:
              web_search_enabled: true
              web_search_strategy: explicit
              web_search_context_size: high
              web_search_allow_fallback: false
            """
        )
        config = ConfigLoader()._dict_to_config(data)
        self.assertTrue(config.model.web_search_enabled)
        self.assertEqual(config.model.web_search_strategy, "explicit")
        self.assertEqual(config.model.web_search_context_size, "high")
        self.assertFalse(config.model.web_search_allow_fallback)

    def test_openai_chat_forwards_response_format(self):
        captured = {}

        class _FakeChatCompletions:
            async def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                role="assistant",
                                content='{"ok": true}',
                                tool_calls=None,
                                reasoning_content=None,
                            )
                        )
                    ],
                    model="test",
                )

        provider = OpenAIProvider.__new__(OpenAIProvider)
        BaseProvider.__init__(provider, ModelConfig(provider="openai", name="test"))
        provider._endpoint = SimpleNamespace(
            api_host="https://api.openai.com/v1", api_path="/chat/completions"
        )
        provider._client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeChatCompletions()))
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "test_schema",
                "strict": True,
                "schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}},
            },
        }

        asyncio.run(
            provider.chat(
                "test",
                [{"role": "user", "content": "hi"}],
                options={"response_format": response_format},
            )
        )

        self.assertEqual(captured["response_format"], response_format)

    def test_openai_official_endpoint_declares_structured_output_capability(self):
        provider = OpenAIProvider.__new__(OpenAIProvider)
        BaseProvider.__init__(provider, ModelConfig(provider="openai", name="gpt-4o"))
        provider._endpoint = SimpleNamespace(
            api_host="https://api.openai.com/v1", api_path="/chat/completions"
        )

        self.assertTrue(provider.supports(ProviderCapability.STRUCTURED_OUTPUT))

    def test_responses_converts_response_format_to_text_format(self):
        captured = {}

        class _FakeResponses:
            async def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    output=[
                        SimpleNamespace(
                            type="message",
                            content=[SimpleNamespace(type="output_text", text='{"ok": true}')],
                        )
                    ],
                    model="test",
                )

        provider = OpenAIResponsesProvider.__new__(OpenAIResponsesProvider)
        BaseProvider.__init__(provider, ModelConfig(provider="openai_responses", name="test"))
        provider._endpoint = SimpleNamespace(api_host="https://api.openai.com/v1", api_path="/responses")
        provider._client = SimpleNamespace(responses=_FakeResponses())
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}

        asyncio.run(
            provider.chat(
                "test",
                [{"role": "user", "content": "hi"}],
                options={
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "test_schema",
                            "strict": True,
                            "schema": schema,
                        },
                    }
                },
            )
        )

        self.assertEqual(
            captured["text"],
            {
                "format": {
                    "type": "json_schema",
                    "name": "test_schema",
                    "strict": True,
                    "schema": schema,
                }
            },
        )

    def test_responses_declares_structured_output_capability(self):
        provider = OpenAIResponsesProvider.__new__(OpenAIResponsesProvider)
        BaseProvider.__init__(provider, ModelConfig(provider="openai_responses", name="gpt-4o"))

        self.assertTrue(provider.supports(ProviderCapability.STRUCTURED_OUTPUT))

    def test_openai_custom_api_path_uses_http_post_json(self):
        async def fake_post_json(url, payload, headers, timeout=None):
            self.assertEqual(url, "https://proxy.example.com/custom/chat")
            self.assertEqual(payload["model"], "test")
            self.assertEqual(headers["Authorization"], "Bearer sk-test")
            return {
                "model": "test",
                "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            }

        provider = OpenAIProvider.__new__(OpenAIProvider)
        BaseProvider.__init__(
            provider,
            ModelConfig(
                provider="openai",
                name="test",
                base_url="https://proxy.example.com",
                api_path="/custom/chat",
                api_key="sk-test",
            ),
        )
        provider._endpoint = SimpleNamespace(
            api_host="https://proxy.example.com", api_path="/custom/chat"
        )
        provider._client = None

        async def call():
            with patch("GensokyoAI.core.agent.providers.openai_provider.post_json", fake_post_json):
                return await provider.chat("test", [{"role": "user", "content": "hi"}])

        response = asyncio.run(call())
        self.assertEqual(response.message.content, "ok")

    def test_responses_custom_api_path_uses_http_post_json(self):
        async def fake_post_json(url, payload, headers, timeout=None):
            self.assertEqual(url, "https://proxy.example.com/custom/generate")
            self.assertEqual(payload["model"], "test")
            return {
                "model": "test",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "ok"}],
                    }
                ],
            }

        provider = OpenAIResponsesProvider.__new__(OpenAIResponsesProvider)
        BaseProvider.__init__(
            provider,
            ModelConfig(
                provider="openai_responses",
                name="test",
                base_url="https://proxy.example.com",
                api_path="/custom/generate",
                api_key="sk-test",
            ),
        )
        provider._endpoint = SimpleNamespace(
            api_host="https://proxy.example.com", api_path="/custom/generate"
        )
        provider._client = None

        async def call():
            with patch(
                "GensokyoAI.core.agent.providers.openai_responses_provider.post_json",
                fake_post_json,
            ):
                return await provider.chat("test", [{"role": "user", "content": "hi"}])

        response = asyncio.run(call())
        self.assertEqual(response.message.content, "ok")


if __name__ == "__main__":
    unittest.main()
