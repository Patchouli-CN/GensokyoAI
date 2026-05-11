import unittest
from types import SimpleNamespace
from unittest.mock import patch

from GensokyoAI.core.agent.providers import ProviderDefinition, ProviderFactory
from GensokyoAI.core.agent.providers.base import BaseProvider
from GensokyoAI.core.agent.providers.deepseek_provider import DeepSeekProvider
from GensokyoAI.core.agent.providers.openrouter_provider import OpenRouterProvider
from GensokyoAI.core.agent.types import ProviderCapability
from GensokyoAI.core.config import ModelConfig


class DummyRegistryProvider(BaseProvider):
    async def chat(self, model: str, messages: list[dict], tools=None, options=None, **kwargs):
        raise NotImplementedError

    async def chat_stream(
        self, model: str, messages: list[dict], tools=None, options=None, **kwargs
    ):
        raise NotImplementedError
        yield


class InvalidProvider:
    pass


class ProviderRegistryTests(unittest.TestCase):
    def test_builtin_definitions_have_unique_ids_and_complete_control_plane_metadata(self):
        definitions = {
            k: v for k, v in ProviderFactory.get_all_provider_definitions().items() if v.builtin
        }
        self.assertEqual(len(definitions), len(set(definitions)))

        for provider_id, definition in definitions.items():
            self.assertEqual(definition.id, provider_id)
            self.assertIsInstance(definition, ProviderDefinition)
            self.assertTrue(definition.name)
            self.assertTrue(definition.protocol)
            self.assertTrue(issubclass(definition.provider_class, BaseProvider))
            self.assertIsInstance(definition.default_headers, dict)
            self.assertIsInstance(definition.capabilities, frozenset)
            self.assertTrue(definition.capabilities)
            self.assertFalse(ProviderCapability.unknown(definition.capabilities))
            self.assertIsNotNone(definition.dependency_key)
            self.assertIsNotNone(definition.model_registry_id)

    def test_builtin_definitions_capture_provider_defaults_and_capabilities(self):
        openrouter = ProviderFactory.get_provider_definition("openrouter")
        assert openrouter is not None
        self.assertIs(openrouter.provider_class, OpenRouterProvider)
        self.assertEqual(openrouter.default_base_url, OpenRouterProvider.DEFAULT_BASE_URL)
        self.assertEqual(openrouter.default_api_path, "/chat/completions")
        self.assertEqual(openrouter.default_headers, OpenRouterProvider.DEFAULT_HEADERS)
        self.assertEqual(openrouter.dependency_key, "openai")
        self.assertEqual(openrouter.model_registry_id, "openrouter")
        self.assertIn(ProviderCapability.TOOLS, openrouter.capabilities)

        deepseek = ProviderFactory.get_provider_definition("deepseek")
        assert deepseek is not None
        self.assertIs(deepseek.provider_class, DeepSeekProvider)
        self.assertEqual(deepseek.default_base_url, DeepSeekProvider.DEFAULT_BASE_URL)
        self.assertEqual(deepseek.default_api_path, "/chat/completions")
        self.assertEqual(deepseek.dependency_key, "openai")
        self.assertEqual(deepseek.model_registry_id, "deepseek")
        self.assertIn(ProviderCapability.REASONING, deepseek.capabilities)

    def test_provider_capability_aliases_are_normalized_for_contract_metadata(self):
        definition = ProviderDefinition(
            id="alias_contract",
            name="Alias Contract",
            protocol="test",
            provider_class=DummyRegistryProvider,
            capabilities=frozenset({"tool_calling", "embedding", "json-schema", "websearch"}),
            builtin=False,
        )

        self.assertEqual(
            definition.capabilities,
            frozenset(
                {
                    ProviderCapability.TOOLS,
                    ProviderCapability.EMBEDDINGS,
                    ProviderCapability.STRUCTURED_OUTPUT,
                    ProviderCapability.WEB_SEARCH,
                }
            ),
        )

    def test_base_provider_supports_uses_normalized_capability_aliases(self):
        provider = DummyRegistryProvider(
            ModelConfig(
                provider="dummy",
                name="dummy-model",
                model_capabilities_add=["tool-calling"],
            )
        )

        self.assertTrue(provider.supports(ProviderCapability.TOOLS))
        self.assertTrue(provider.supports("tool_calls"))

    def test_available_providers_remains_list_of_registered_provider_ids(self):
        available = ProviderFactory.available_providers()
        definitions = ProviderFactory.get_all_provider_definitions()

        self.assertIsInstance(available, list)
        self.assertEqual(available, list(definitions.keys()))
        self.assertIn("ollama", available)
        self.assertIn("deepseek", available)

    def test_create_remains_backward_compatible_and_returns_base_provider(self):
        with patch.dict(
            "sys.modules",
            {"openai": SimpleNamespace(AsyncOpenAI=lambda **kwargs: SimpleNamespace())},
        ):
            provider = ProviderFactory.create(
                ModelConfig(provider="deepseek", name="deepseek-chat", api_key="test-key")
            )

        self.assertIsInstance(provider, BaseProvider)
        self.assertIsInstance(provider, DeepSeekProvider)

    def test_custom_provider_registration_creates_custom_definition(self):
        provider_id = "registry_test_custom_provider"
        if provider_id not in ProviderFactory.available_providers():
            ProviderFactory.register(provider_id, DummyRegistryProvider)

        definition = ProviderFactory.get_provider_definition(provider_id)
        assert definition is not None
        self.assertEqual(definition.id, provider_id)
        self.assertEqual(definition.name, provider_id)
        self.assertEqual(definition.protocol, "custom")
        self.assertIs(definition.provider_class, DummyRegistryProvider)
        self.assertFalse(definition.builtin)
        self.assertEqual(definition.capabilities, frozenset())

    def test_custom_provider_cannot_override_builtin_provider_id(self):
        with self.assertRaisesRegex(ValueError, "内置 Provider ID"):
            ProviderFactory.register("deepseek", DummyRegistryProvider)

    def test_custom_provider_cannot_reuse_existing_custom_provider_id(self):
        provider_id = "registry_test_duplicate_custom_provider"
        if provider_id not in ProviderFactory.available_providers():
            ProviderFactory.register(provider_id, DummyRegistryProvider)

        with self.assertRaisesRegex(ValueError, "Provider ID 已注册"):
            ProviderFactory.register(provider_id, DummyRegistryProvider)

    def test_custom_provider_must_inherit_base_provider(self):
        with self.assertRaises(TypeError):
            ProviderFactory.register("registry_test_invalid_provider", InvalidProvider)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
