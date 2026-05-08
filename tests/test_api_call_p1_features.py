import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from GensokyoAI.core.agent.model_client import ModelClient
from GensokyoAI.core.agent.providers.base import BaseProvider
from GensokyoAI.core.agent.providers.openai_provider import OpenAIProvider
from GensokyoAI.core.agent.providers.openai_responses_provider import OpenAIResponsesProvider
from GensokyoAI.core.agent.providers.deepseek_provider import DeepSeekProvider
from GensokyoAI.core.agent.providers.ollama_provider import OllamaProvider
from GensokyoAI.core.agent.providers.gemini_provider import GeminiProvider
from GensokyoAI.core.agent.providers.claude_provider import ClaudeProvider
from GensokyoAI.core.agent.types import ModelInfo, ProviderCapability, StreamChunk
from GensokyoAI.core.config import EmbeddingConfig, ModelConfig


class _EmbeddingsProvider(BaseProvider):
    @property
    def capabilities(self) -> set[str]:
        return super().capabilities | {ProviderCapability.EMBEDDINGS}

    async def chat(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        raise NotImplementedError

    async def chat_stream(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        if False:
            yield None


class _NoEmbeddingsProvider(BaseProvider):
    async def chat(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        raise NotImplementedError

    async def chat_stream(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        if False:
            yield None


class _FailOnceStreamProvider(BaseProvider):
    calls = 0

    async def chat(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        raise NotImplementedError

    async def chat_stream(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
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
                    owned_by="tester",
                    context_length=128000,
                    input_modalities=["text", "image"],
                    pricing={"internal_reasoning": "1"},
                )
            ]
        )


class _FakeOpenAIClient:
    def __init__(self):
        self.models = _FakeModelsClient()


class P1ApiCallFeatureTests(unittest.TestCase):
    def test_stream_chunk_new_fields_are_optional_and_settable(self):
        chunk = StreamChunk(type="finish", status="done", usage={"total_tokens": 3}, finish_reason="stop")
        self.assertEqual(chunk.type, "finish")
        self.assertEqual(chunk.status, "done")
        self.assertEqual(chunk.usage["total_tokens"], 3)
        self.assertEqual(chunk.finish_reason, "stop")

    def test_base_provider_capabilities_and_supports(self):
        provider = _NoEmbeddingsProvider(ModelConfig())
        self.assertTrue(provider.supports(ProviderCapability.CHAT))
        self.assertTrue(provider.supports(ProviderCapability.STREAM))
        self.assertFalse(provider.supports(ProviderCapability.EMBEDDINGS))

    def test_builtin_provider_capability_declarations(self):
        checks = [
            (OpenAIProvider, {ProviderCapability.EMBEDDINGS, ProviderCapability.CUSTOM_ENDPOINT}),
            (OpenAIResponsesProvider, {ProviderCapability.RESPONSES_API, ProviderCapability.REASONING}),
            (DeepSeekProvider, {ProviderCapability.REASONING}),
            (OllamaProvider, {ProviderCapability.EMBEDDINGS}),
            (GeminiProvider, {ProviderCapability.VISION, ProviderCapability.EMBEDDINGS}),
            (ClaudeProvider, {ProviderCapability.REASONING, ProviderCapability.VISION}),
        ]
        for provider_cls, expected in checks:
            provider = provider_cls.__new__(provider_cls)
            BaseProvider.__init__(provider, ModelConfig(provider="test", name="test"))
            self.assertTrue(expected.issubset(provider.capabilities), provider_cls.__name__)

    def test_model_client_supports_embeddings_uses_capability(self):
        client = ModelClient.__new__(ModelClient)
        client.config = ModelConfig()
        client._embedding_config = EmbeddingConfig(name="embed-model")
        client._embedding_provider = _EmbeddingsProvider(ModelConfig())
        client._get_embedding_provider = lambda: (client._embedding_provider, ModelConfig(name="embed-model"))
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
            return [chunk async for chunk in client.chat_stream([{"role": "user", "content": "hi"}])]

        chunks = asyncio.run(collect())
        self.assertEqual(chunks[0].type, "status")
        self.assertEqual(chunks[0].status, "retrying")
        self.assertEqual(chunks[1].content, "ok")


if __name__ == "__main__":
    unittest.main()
