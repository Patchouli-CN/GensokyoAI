import asyncio
import unittest

from GensokyoAI.core.agent.model_registry import ModelMetadataOverride, ModelRegistryService
from GensokyoAI.core.agent.providers.base import BaseProvider
from GensokyoAI.core.agent.types import ModelInfo, ProviderCapability
from GensokyoAI.core.config import ModelConfig


class StaticModelProvider(BaseProvider):
    models: list[ModelInfo] = []
    calls: int = 0

    async def chat(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        raise NotImplementedError

    async def chat_stream(
        self, model: str, messages: list[dict], tools=None, options=None, **kwargs
    ):
        raise NotImplementedError
        yield

    async def list_models(self) -> list[ModelInfo]:
        type(self).calls += 1
        return [
            ModelInfo(
                id=model.id,
                name=model.name,
                context_window=model.context_window,
                capabilities=list(model.capabilities),
                owned_by=model.owned_by,
                metadata=dict(model.metadata),
            )
            for model in type(self).models
        ]


class FailingModelProvider(BaseProvider):
    calls: int = 0

    async def chat(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        raise NotImplementedError

    async def chat_stream(
        self, model: str, messages: list[dict], tools=None, options=None, **kwargs
    ):
        raise NotImplementedError
        yield

    async def list_models(self) -> list[ModelInfo]:
        type(self).calls += 1
        raise RuntimeError("offline")


class SequencedProvider(BaseProvider):
    responses: list[list[ModelInfo] | Exception] = []
    calls: int = 0

    async def chat(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        raise NotImplementedError

    async def chat_stream(
        self, model: str, messages: list[dict], tools=None, options=None, **kwargs
    ):
        raise NotImplementedError
        yield

    async def list_models(self) -> list[ModelInfo]:
        type(self).calls += 1
        response = type(self).responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return [
            ModelInfo(
                id=model.id,
                name=model.name,
                context_window=model.context_window,
                capabilities=list(model.capabilities),
                owned_by=model.owned_by,
                metadata=dict(model.metadata),
            )
            for model in response
        ]


class ModelRegistryServiceTests(unittest.TestCase):
    def setUp(self):
        StaticModelProvider.calls = 0
        StaticModelProvider.models = []
        FailingModelProvider.calls = 0
        SequencedProvider.calls = 0
        SequencedProvider.responses = []

    def test_list_models_uses_provider_metadata_without_builtin_snapshot_enrichment(self):
        StaticModelProvider.models = [
            ModelInfo(
                id="openai/gpt-4o",
                name="Remote GPT-4o",
                context_window=256000,
                capabilities=[ProviderCapability.CHAT, ProviderCapability.WEB_SEARCH],
                owned_by="remote-openai",
                metadata={"remote": True},
            )
        ]
        service = ModelRegistryService(provider_builder=lambda config: StaticModelProvider(config))

        models = asyncio.run(
            service.list_models(ModelConfig(provider="openrouter", name="openai/gpt-4o"))
        )
        model = ModelRegistryService.match_model(models, "openai/gpt-4o")

        assert model is not None
        self.assertEqual(model.name, "Remote GPT-4o")
        self.assertEqual(model.context_window, 256000)
        self.assertEqual(model.owned_by, "remote-openai")
        self.assertTrue(model.metadata["remote"])
        self.assertEqual(model.metadata["model_registry_id"], "openrouter")
        self.assertIn(ProviderCapability.WEB_SEARCH, model.capabilities)
        self.assertNotIn(ProviderCapability.VISION, model.capabilities)
        self.assertNotIn(ProviderCapability.STRUCTURED_OUTPUT, model.capabilities)

    def test_user_override_has_highest_precedence(self):
        StaticModelProvider.models = [
            ModelInfo(
                id="openai/gpt-4o",
                name="Remote GPT-4o",
                context_window=128000,
                capabilities=[ProviderCapability.CHAT, ProviderCapability.WEB_SEARCH],
                metadata={"remote": True},
            )
        ]
        service = ModelRegistryService(provider_builder=lambda config: StaticModelProvider(config))
        config = ModelConfig(
            provider="openrouter",
            name="openai/gpt-4o",
            model_capabilities_add=["custom_config_capability"],
            model_capabilities_remove=[ProviderCapability.WEB_SEARCH],
        )

        info = asyncio.run(
            service.get_model_info(
                config,
                overrides={
                    "openai/gpt-4o": ModelMetadataOverride(
                        id="openai/gpt-4o",
                        name="User Fixed GPT-4o",
                        context_window=64000,
                        capabilities_add=frozenset({"user_capability"}),
                        capabilities_remove=frozenset({ProviderCapability.VISION}),
                        owned_by="user",
                        metadata={"note": "fixed"},
                    )
                },
            )
        )

        self.assertEqual(info.name, "User Fixed GPT-4o")
        self.assertEqual(info.context_window, 64000)
        self.assertEqual(info.owned_by, "user")
        self.assertIn("custom_config_capability", info.capabilities)
        self.assertIn("user_capability", info.capabilities)
        self.assertNotIn(ProviderCapability.WEB_SEARCH, info.capabilities)
        self.assertNotIn(ProviderCapability.VISION, info.capabilities)
        self.assertTrue(info.metadata["overridden"])
        self.assertEqual(info.metadata["note"], "fixed")

    def test_remote_failure_uses_cached_models_without_clearing_cache(self):
        SequencedProvider.responses = [
            [
                ModelInfo(
                    id="openai/remote-only", name="remote", capabilities=[ProviderCapability.CHAT]
                )
            ],
            RuntimeError("offline"),
        ]
        service = ModelRegistryService(provider_builder=lambda config: SequencedProvider(config))
        config = ModelConfig(provider="openrouter", name="openai/remote-only")

        first = asyncio.run(service.list_models(config, refresh=True))
        second = asyncio.run(service.list_models(config, refresh=True))

        self.assertEqual(SequencedProvider.calls, 2)
        self.assertIsNotNone(ModelRegistryService.match_model(first, "openai/remote-only"))
        self.assertIsNotNone(ModelRegistryService.match_model(second, "openai/remote-only"))

    def test_remote_failure_without_cache_falls_back_to_heuristic_current_model(self):
        service = ModelRegistryService(provider_builder=lambda config: FailingModelProvider(config))
        config = ModelConfig(provider="openrouter", name="anthropic/claude-3.5-sonnet")

        models = asyncio.run(service.list_models(config, refresh=True))

        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].id, "anthropic/claude-3.5-sonnet")
        self.assertIsNone(models[0].owned_by)
        self.assertTrue(models[0].metadata["fallback"])
        self.assertEqual(models[0].metadata["source"], "heuristic")

    def test_unknown_provider_failure_uses_heuristic_current_model(self):
        service = ModelRegistryService(provider_builder=lambda config: FailingModelProvider(config))
        config = ModelConfig(provider="unknown_provider", name="my-reasoning-vision-model")

        models = asyncio.run(service.list_models(config, refresh=True))

        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].id, "my-reasoning-vision-model")
        self.assertIn(ProviderCapability.REASONING, models[0].capabilities)
        self.assertIn(ProviderCapability.VISION, models[0].capabilities)
        self.assertTrue(models[0].metadata["fallback"])
        self.assertEqual(models[0].metadata["source"], "heuristic")

    def test_match_model_prefers_exact_then_boundary_prefix(self):
        models = [
            ModelInfo(id="models/gemini-2.5-pro", name="Gemini Pro"),
            ModelInfo(id="deepseek-reasoner", name="DeepSeek Reasoner"),
        ]

        exact = ModelRegistryService.match_model(models, "models/gemini-2.5-pro")
        prefix = ModelRegistryService.match_model(models, "gemini-2.5-pro-latest")
        reverse_prefix = ModelRegistryService.match_model(models, "deepseek-reasoner-v1")
        no_match = ModelRegistryService.match_model(models, "gemini2.5pro")

        assert exact is not None
        assert prefix is not None
        assert reverse_prefix is not None
        self.assertEqual(exact.id, "models/gemini-2.5-pro")
        self.assertEqual(prefix.id, "models/gemini-2.5-pro")
        self.assertEqual(reverse_prefix.id, "deepseek-reasoner")
        self.assertIsNone(no_match)

    def test_model_capability_aliases_are_normalized_across_remote_config_and_overrides(self):
        StaticModelProvider.models = [
            ModelInfo(
                id="alias-model",
                name="Alias Model",
                capabilities=["tool-calling", "json-schema", "websearch"],
            )
        ]
        service = ModelRegistryService(provider_builder=lambda config: StaticModelProvider(config))
        config = ModelConfig(
            provider="openai",
            name="alias-model",
            model_capabilities_add=["embedding"],
            model_capabilities_remove=["tool_calls"],
        )

        info = asyncio.run(
            service.get_model_info(
                config,
                overrides={
                    "alias-model": {
                        "capabilities_add": ["function_calling", "structured_outputs"],
                        "capabilities_remove": ["web-search"],
                    }
                },
            )
        )

        self.assertIn(ProviderCapability.EMBEDDINGS, info.capabilities)
        self.assertIn(ProviderCapability.STRUCTURED_OUTPUT, info.capabilities)
        self.assertIn(ProviderCapability.TOOLS, info.capabilities)
        self.assertNotIn(ProviderCapability.WEB_SEARCH, info.capabilities)
        self.assertNotIn("tool-calling", info.capabilities)
        self.assertNotIn("json-schema", info.capabilities)

    def test_cache_avoids_provider_call_when_refresh_false(self):
        StaticModelProvider.models = [ModelInfo(id="gpt-4o", name="gpt-4o")]
        service = ModelRegistryService(provider_builder=lambda config: StaticModelProvider(config))
        config = ModelConfig(provider="openai", name="gpt-4o")

        asyncio.run(service.list_models(config))
        asyncio.run(service.list_models(config))

        self.assertEqual(StaticModelProvider.calls, 1)


if __name__ == "__main__":
    unittest.main()
