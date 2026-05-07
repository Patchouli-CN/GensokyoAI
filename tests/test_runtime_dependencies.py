import asyncio
import unittest
from unittest.mock import patch

from GensokyoAI.runtime.dependencies import (
    OPTIONAL_PROVIDER_DEPENDENCIES,
    DependencyError,
    dependency_status,
    packages_for_providers,
)
from GensokyoAI.runtime.rpc import (
    RpcMethodNotFoundError,
    dispatch_rpc,
    legacy_rpc_methods,
    resolve_rpc_handler,
    rpc_methods,
)
from GensokyoAI.runtime.service import RuntimeService


class RuntimeDependencyTests(unittest.TestCase):
    def test_dependency_mapping_includes_expected_provider_aliases(self):
        self.assertEqual(OPTIONAL_PROVIDER_DEPENDENCIES["deepseek"], ["openai>=1.0.0"])
        self.assertEqual(
            packages_for_providers(["openai", "deepseek", "openai_responses"]),
            ["openai>=1.0.0"],
        )

    def test_dependency_status_reports_missing_imports(self):
        def fake_find_spec(name):
            return object() if name == "openai" else None

        with patch("importlib.util.find_spec", side_effect=fake_find_spec):
            status = dependency_status(["deepseek", "claude"])

        self.assertTrue(status["providers"]["deepseek"]["installed"])
        self.assertFalse(status["providers"]["claude"]["installed"])
        self.assertEqual(status["providers"]["claude"]["missing_imports"], ["anthropic"])

    def test_dependency_status_rejects_unknown_provider(self):
        with self.assertRaises(DependencyError) as ctx:
            dependency_status(["not-a-provider"])

        self.assertEqual(ctx.exception.code, "unsupported_provider_dependency")
        self.assertIn("not-a-provider", ctx.exception.details["providers"])

    def test_runtime_service_exposes_dependency_methods(self):
        service = RuntimeService()

        async def run():
            with patch("importlib.util.find_spec", return_value=None):
                status = await service.handle(
                    "dependency.status",
                    {"providers": ["openai"]},
                )
            legacy = await service.handle("dependency_status", {"providers": []})
            info = await service.handle("runtime.info")
            return status, legacy, info

        status, legacy, info = asyncio.run(run())

        self.assertIn("openai", status["providers"])
        self.assertEqual(legacy["providers"], {})
        self.assertIn("dependency.status", info["methods"])
        self.assertIn("install_dependencies", info["legacy_methods"])


class RuntimeRpcDispatchTests(unittest.TestCase):
    def test_rpc_method_lists_are_owned_by_runtime_rpc_module(self):
        self.assertIn("runtime.info", rpc_methods())
        self.assertIn("dependency.status", rpc_methods())
        self.assertNotIn("init", rpc_methods())
        self.assertIn("init", legacy_rpc_methods())
        self.assertIn("install_dependencies", legacy_rpc_methods())

    def test_resolve_rpc_handler_maps_namespaced_and_legacy_methods(self):
        service = RuntimeService()

        self.assertEqual(resolve_rpc_handler(service, "runtime.info").__name__, "info")
        self.assertEqual(resolve_rpc_handler(service, "init").__name__, "init")
        self.assertEqual(
            resolve_rpc_handler(service, "dependency.status").__name__,
            "dependency_status",
        )

    def test_dispatch_rpc_raises_structured_method_not_found_error(self):
        service = RuntimeService()

        async def run():
            await dispatch_rpc(service, "not.registered", {})

        with self.assertRaises(RpcMethodNotFoundError) as ctx:
            asyncio.run(run())

        self.assertEqual(ctx.exception.code, "method_not_found")
        self.assertTrue(ctx.exception.recoverable)
        self.assertEqual(ctx.exception.details["method"], "not.registered")
        self.assertIn("runtime.info", ctx.exception.details["allowed_methods"])


if __name__ == "__main__":
    unittest.main()
