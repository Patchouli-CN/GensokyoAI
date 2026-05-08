import asyncio
import unittest
from types import SimpleNamespace

from GensokyoAI.core.agent.model_client import ModelClient
from GensokyoAI.core.agent.providers import ProviderFactory
from GensokyoAI.core.agent.providers.base import BaseProvider
from GensokyoAI.core.agent.types import ProviderCapability, UnifiedEmbeddingResponse
from GensokyoAI.core.config import EmbeddingConfig, ModelConfig
from GensokyoAI.core.exceptions import ModelError


class RetryableProvider(BaseProvider):
    calls = 0

    async def chat(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        self.__class__.calls += 1
        if self.__class__.calls == 1:
            error = RuntimeError("server failed")
            error.status_code = 502
            error.response_body = "<!doctype html><html>bad gateway</html>"
            raise error
        return SimpleNamespace(
            message=SimpleNamespace(content="ok"),
            model=model,
            done=True,
        )

    async def chat_stream(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        if False:
            yield None


class NonRetryableProvider(BaseProvider):
    calls = 0

    async def chat(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        self.__class__.calls += 1
        error = RuntimeError("bad request")
        error.status_code = 400
        error.response_body = "bad params"
        raise error

    async def chat_stream(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        if False:
            yield None


class Retryable429Provider(BaseProvider):
    calls = 0

    async def chat(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        self.__class__.calls += 1
        if self.__class__.calls == 1:
            error = RuntimeError("rate limited")
            error.status_code = 429
            error.response_body = "retry later"
            raise error
        return SimpleNamespace(
            message=SimpleNamespace(content="ok429"),
            model=model,
            done=True,
        )

    async def chat_stream(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        if False:
            yield None


class RetryableEmbeddingProvider(BaseProvider):
    calls = 0

    @property
    def capabilities(self) -> set[str]:
        return super().capabilities | {ProviderCapability.EMBEDDINGS}

    async def chat(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        raise NotImplementedError

    async def chat_stream(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        if False:
            yield None

    async def embeddings(self, model: str, prompt: str, **kwargs):
        self.__class__.calls += 1
        if self.__class__.calls == 1:
            error = RuntimeError("embedding server failed")
            error.status_code = 502
            error.response_body = "<!doctype html><html>bad gateway</html>"
            raise error
        return UnifiedEmbeddingResponse(embedding=[1.0, 2.0], model=model)


class FailingEmbeddingProvider(BaseProvider):
    @property
    def capabilities(self) -> set[str]:
        return super().capabilities | {ProviderCapability.EMBEDDINGS}

    async def chat(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        raise NotImplementedError

    async def chat_stream(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        if False:
            yield None

    async def embeddings(self, model: str, prompt: str, **kwargs):
        error = RuntimeError("bad embedding request")
        error.status_code = 400
        error.response_body = "bad embedding params"
        raise error


class _CollectingEventBus:
    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)


class ModelClientRetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ProviderFactory.register("retryable_test", RetryableProvider)
        ProviderFactory.register("non_retryable_test", NonRetryableProvider)
        ProviderFactory.register("retryable_429_test", Retryable429Provider)
        ProviderFactory.register("retryable_embedding_test", RetryableEmbeddingProvider)
        ProviderFactory.register("failing_embedding_test", FailingEmbeddingProvider)

    def test_retries_5xx_and_succeeds(self):
        RetryableProvider.calls = 0
        client = ModelClient(
            ModelConfig(
                provider="retryable_test",
                name="test-model",
                retry_max_attempts=2,
                retry_initial_delay=0,
            )
        )

        response = asyncio.run(client.chat([{"role": "user", "content": "hi"}]))

        self.assertEqual(response.message.content, "ok")
        self.assertEqual(RetryableProvider.calls, 2)

    def test_does_not_retry_400_and_sanitizes_error(self):
        NonRetryableProvider.calls = 0
        client = ModelClient(
            ModelConfig(
                provider="non_retryable_test",
                name="test-model",
                retry_max_attempts=3,
                retry_initial_delay=0,
            )
        )

        with self.assertRaises(ModelError) as ctx:
            asyncio.run(client.chat([{"role": "user", "content": "hi"}]))

        self.assertEqual(NonRetryableProvider.calls, 1)
        self.assertIn("API 状态码 400", str(ctx.exception))
        self.assertIn("bad params", str(ctx.exception))

    def test_custom_retry_status_codes_can_retry_429(self):
        Retryable429Provider.calls = 0
        client = ModelClient(
            ModelConfig(
                provider="retryable_429_test",
                name="test-model",
                retry_max_attempts=2,
                retry_initial_delay=0,
                retry_status_codes=[429],
            )
        )

        response = asyncio.run(client.chat([{"role": "user", "content": "hi"}]))

        self.assertEqual(response.message.content, "ok429")
        self.assertEqual(Retryable429Provider.calls, 2)

    def test_embeddings_retries_5xx_and_succeeds(self):
        RetryableEmbeddingProvider.calls = 0
        client = ModelClient(
            ModelConfig(
                provider="retryable_embedding_test",
                name="chat-model",
                retry_max_attempts=2,
                retry_initial_delay=0,
            ),
            embedding_config=EmbeddingConfig(provider="retryable_embedding_test", name="embed-model"),
        )

        response = asyncio.run(client.embeddings("hello"))

        self.assertEqual(response.embedding, [1.0, 2.0])
        self.assertEqual(RetryableEmbeddingProvider.calls, 2)

    def test_embeddings_failure_publishes_structured_error_event(self):
        event_bus = _CollectingEventBus()
        client = ModelClient(
            ModelConfig(
                provider="failing_embedding_test",
                name="chat-model",
                retry_max_attempts=2,
                retry_initial_delay=0,
            ),
            event_bus=event_bus,
            embedding_config=EmbeddingConfig(provider="failing_embedding_test", name="embed-model"),
        )

        with self.assertRaises(ModelError):
            asyncio.run(client.embeddings("hello"))

        self.assertTrue(event_bus.events)
        data = event_bus.events[-1].data
        self.assertEqual(data["context"], "embeddings")
        self.assertEqual(data["status_code"], 400)
        self.assertEqual(data["prompt_length"], 5)
        self.assertEqual(data["provider"], "failing_embedding_test")
        self.assertEqual(data["model"], "embed-model")


if __name__ == "__main__":
    unittest.main()
