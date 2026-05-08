import asyncio
import unittest
from types import SimpleNamespace

from GensokyoAI.core.agent.model_client import ModelClient
from GensokyoAI.core.agent.providers import ProviderFactory
from GensokyoAI.core.agent.providers.base import BaseProvider
from GensokyoAI.core.config import ModelConfig
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


class ModelClientRetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ProviderFactory.register("retryable_test", RetryableProvider)
        ProviderFactory.register("non_retryable_test", NonRetryableProvider)

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


if __name__ == "__main__":
    unittest.main()
