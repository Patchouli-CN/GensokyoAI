import asyncio
import json
import tempfile
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import yaml
from unittest.mock import patch

from GensokyoAI.core.agent.types import ModelInfo, ProviderCapability, StreamChunk
from GensokyoAI.core.events import Event, EventBus, SystemEvent
from GensokyoAI.core.config import ConfigLoader, ModelConfig
from GensokyoAI.session.context import SessionContext
from GensokyoAI.session.persistence import SessionPersistence
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
from GensokyoAI.tools.errors import ToolError, ToolExecutionError
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

    def test_runtime_service_exposes_dependency_and_model_methods(self):
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
        self.assertIn("model.list", info["methods"])
        self.assertIn("model.info", info["methods"])
        self.assertIn("install_dependencies", info["legacy_methods"])


class FakeModelRegistry:
    def __init__(self):
        self.list_calls = []
        self.info_calls = []

    async def list_models(self, config, *, refresh=False, overrides=None):
        self.list_calls.append((config, refresh, overrides))
        return [
            ModelInfo(
                id="gpt-test",
                name="GPT Test",
                context_window=4096,
                capabilities=[ProviderCapability.CHAT, ProviderCapability.TOOLS],
                owned_by="tests",
                metadata={"source": "fake"},
            )
        ]

    async def get_model_info(self, config, model_id=None, *, refresh=False, overrides=None):
        self.info_calls.append((config, model_id, refresh, overrides))
        return ModelInfo(
            id=model_id or config.name,
            name="Selected Test Model",
            context_window=8192,
            capabilities=[ProviderCapability.CHAT],
            owned_by="tests",
            metadata={"selected": True},
        )


class SessionPersistenceIndexTests(unittest.TestCase):
    def test_delete_session_uses_index_before_removing_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            persistence = SessionPersistence(Path(tmp))
            session = SessionContext(character_id="reimu")
            persistence.save_session(session)
            session_file = Path(tmp) / "reimu" / f"{session.session_id}.json"
            self.assertTrue(session_file.exists())
            self.assertEqual(persistence._session_index[session.session_id], "reimu")

            deleted = persistence.delete_session(session.session_id)

            self.assertTrue(deleted)
            self.assertFalse(session_file.exists())
            self.assertNotIn(session.session_id, persistence._session_index)

    def test_delete_session_async_uses_index_before_removing_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            persistence = SessionPersistence(Path(tmp))
            session = SessionContext(character_id="marisa")
            persistence.save_session(session)
            session_file = Path(tmp) / "marisa" / f"{session.session_id}.json"

            async def run():
                return await persistence.delete_session_async(session.session_id)

            deleted = asyncio.run(run())

            self.assertTrue(deleted)
            self.assertFalse(session_file.exists())
            self.assertNotIn(session.session_id, persistence._session_index)


    def test_save_session_creates_backup_before_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            persistence = SessionPersistence(Path(tmp))
            session = SessionContext(character_id="reimu", metadata={"title": "old"})
            persistence.save_session(session)
            session.metadata["title"] = "new"

            persistence.save_session(session)

            session_file = Path(tmp) / "reimu" / f"{session.session_id}.json"
            backup_file = session_file.with_name(f"{session_file.name}.bak")
            self.assertTrue(backup_file.exists())
            backup_data = json.loads(backup_file.read_text(encoding="utf-8"))
            current_data = json.loads(session_file.read_text(encoding="utf-8"))
            self.assertEqual(backup_data["session"]["metadata"]["title"], "old")
            self.assertEqual(current_data["session"]["metadata"]["title"], "new")
            self.assertFalse(list(session_file.parent.glob("*.tmp")))

    def test_load_messages_recovers_from_backup_when_json_is_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            persistence = SessionPersistence(Path(tmp))
            session = SessionContext(character_id="reimu")
            persistence.save_session(session)
            persistence.save_messages(session.session_id, [{"role": "user", "content": "backup"}])
            session_file = Path(tmp) / "reimu" / f"{session.session_id}.json"
            backup_file = session_file.with_name(f"{session_file.name}.bak")
            self.assertTrue(backup_file.exists())
            session_file.write_text("{ broken json", encoding="utf-8")

            messages = persistence.load_messages(session.session_id)

            self.assertEqual(messages, [])
            restored_data = json.loads(session_file.read_text(encoding="utf-8"))
            self.assertEqual(restored_data["session"]["session_id"], session.session_id)
            self.assertFalse((session_file.parent / "quarantine").exists())

    def test_load_session_quarantines_corrupt_json_when_backup_is_unusable(self):
        with tempfile.TemporaryDirectory() as tmp:
            persistence = SessionPersistence(Path(tmp))
            session = SessionContext(character_id="marisa")
            persistence.save_session(session)
            session_file = Path(tmp) / "marisa" / f"{session.session_id}.json"
            session_file.write_text("{ broken json", encoding="utf-8")
            session_file.with_name(f"{session_file.name}.bak").write_text("{ also broken", encoding="utf-8")

            with self.assertRaises(json.JSONDecodeError):
                persistence.load_session("marisa", session.session_id)

            self.assertFalse(session_file.exists())
            quarantined = list((Path(tmp) / "marisa" / "quarantine").glob("*.bad"))
            self.assertEqual(len(quarantined), 1)
            self.assertIn(session.session_id, quarantined[0].name)

    def test_async_load_messages_recovers_from_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            persistence = SessionPersistence(Path(tmp))
            session = SessionContext(character_id="sanae")
            persistence.save_session(session)
            persistence.save_messages(session.session_id, [{"role": "user", "content": "backup"}])
            session_file = Path(tmp) / "sanae" / f"{session.session_id}.json"
            session_file.write_text("{ broken json", encoding="utf-8")

            messages = asyncio.run(persistence.load_messages_async(session.session_id))

            self.assertEqual(messages, [])
            self.assertTrue(session_file.exists())


class PackagingConfigurationTests(unittest.TestCase):
    def _load_pyproject(self) -> dict[str, Any]:
        with open(Path("pyproject.toml"), "rb") as f:
            return tomllib.load(f)

    def _requirements_entries(self) -> list[str]:
        entries = []
        for line in Path("requirements.txt").read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            entries.append(stripped.split("#", 1)[0].strip())
        return entries

    def test_requirements_are_minimal_core_dependencies_without_provider_sdks(self):
        requirements = self._requirements_entries()

        self.assertIn("aiohttp>=3.9", requirements)
        self.assertIn("ayafileio>=1.1.4", requirements)
        self.assertNotIn("ollama", requirements)
        self.assertNotIn("openai", requirements)
        self.assertNotIn("anthropic", requirements)
        self.assertNotIn("google-genai", requirements)

    def test_pyproject_declares_default_all_and_dev_dependency_groups(self):
        pyproject = self._load_pyproject()
        optional = pyproject["project"]["optional-dependencies"]
        groups = pyproject["dependency-groups"]

        self.assertEqual(optional["default"], ["ollama"])
        self.assertEqual(optional["deepseek"], OPTIONAL_PROVIDER_DEPENDENCIES["deepseek"])
        self.assertEqual(optional["openrouter"], OPTIONAL_PROVIDER_DEPENDENCIES["openrouter"])
        self.assertIn("ollama", optional["all"])
        self.assertIn("openai>=1.0.0", optional["all"])
        self.assertIn("pytest>=8.0", groups["dev"])
        self.assertIn("ruff>=0.6.0", groups["dev"])
        self.assertIn("pyright>=1.1.390", groups["dev"])
        self.assertIn("build>=1.2.0", groups["dev"])
        self.assertEqual(pyproject["tool"]["pytest"]["ini_options"]["testpaths"], ["tests"])
        self.assertNotIn("asyncio_mode", pyproject["tool"]["pytest"]["ini_options"])
        self.assertEqual(pyproject["tool"]["coverage"]["report"]["fail_under"], 45)
        self.assertEqual(pyproject["tool"]["pyright"]["typeCheckingMode"], "basic")


class RuntimeModelRpcTests(unittest.TestCase):
    def test_model_list_and_info_return_json_compatible_model_metadata(self):
        service = RuntimeService()
        fake_registry = FakeModelRegistry()
        cast(Any, service)._model_registry = fake_registry
        cast(Any, service.state).agent = SimpleNamespace(
            config=SimpleNamespace(model=ModelConfig(provider="openai", name="gpt-test"))
        )

        async def run():
            listed = await service.handle(
                "model.list",
                {
                    "refresh": True,
                    "overrides": {
                        "gpt-test": {
                            "capabilities_add": ["custom"],
                        }
                    },
                },
            )
            info = await service.handle("model.info", {"model_id": "gpt-test-v2"})
            return listed, info

        listed, info = asyncio.run(run())

        self.assertEqual(listed["provider"], "openai")
        self.assertEqual(listed["model"], "gpt-test")
        self.assertEqual(listed["models"][0]["id"], "gpt-test")
        self.assertEqual(listed["models"][0]["context_window"], 4096)
        self.assertIn(ProviderCapability.TOOLS, listed["models"][0]["capabilities"])
        self.assertEqual(listed["models"][0]["metadata"], {"source": "fake"})
        self.assertTrue(fake_registry.list_calls[0][1])
        self.assertIn("gpt-test", fake_registry.list_calls[0][2])

        self.assertEqual(info["provider"], "openai")
        self.assertEqual(info["requested_model"], "gpt-test-v2")
        self.assertEqual(info["model"]["id"], "gpt-test-v2")
        self.assertEqual(info["model"]["metadata"], {"selected": True})
        self.assertEqual(fake_registry.info_calls[0][1], "gpt-test-v2")


class RuntimeRpcDispatchTests(unittest.TestCase):
    def test_rpc_method_lists_are_owned_by_runtime_rpc_module(self):
        self.assertIn("runtime.info", rpc_methods())
        self.assertIn("dependency.status", rpc_methods())
        self.assertIn("model.list", rpc_methods())
        self.assertIn("model.info", rpc_methods())
        self.assertIn("agent.send_message_stream", rpc_methods())
        self.assertIn("session.current", rpc_methods())
        self.assertIn("session.delete", rpc_methods())
        self.assertIn("session.export", rpc_methods())
        self.assertIn("session.rename", rpc_methods())
        self.assertIn("session.rollback", rpc_methods())
        self.assertNotIn("init", rpc_methods())
        self.assertIn("init", legacy_rpc_methods())
        self.assertIn("install_dependencies", legacy_rpc_methods())
        self.assertIn("send_message_stream", legacy_rpc_methods())
        self.assertIn("memory.list", rpc_methods())
        self.assertIn("memory.search", rpc_methods())
        self.assertIn("memory.get", rpc_methods())
        self.assertIn("memory.update", rpc_methods())
        self.assertIn("memory.delete", rpc_methods())
        self.assertIn("memory.graph", rpc_methods())

    def test_runtime_protocol_metadata_documents_versions_and_deprecations(self):
        service = RuntimeService()

        async def run():
            return await service.handle("runtime.info")

        info = asyncio.run(run())

        self.assertEqual(info["protocol_version"], "1.1.0")
        self.assertEqual(info["protocol_major_version"], 1)
        self.assertIn("agent.streaming", info["capabilities"])
        self.assertIn("runtime.events", info["capabilities"])
        self.assertIn("memory.management", info["capabilities"])
        self.assertEqual(info["breaking_changes"], [])
        self.assertTrue(info["method_specs"])

        legacy_init = next(item for item in info["deprecated_methods"] if item["method"] == "init")
        self.assertTrue(legacy_init["deprecated"])
        self.assertEqual(legacy_init["replacement"], "agent.init")
        self.assertEqual(legacy_init["remove_after"], "2.0.0")

        runtime_info = next(item for item in info["method_specs"] if item["method"] == "runtime.info")
        self.assertEqual(runtime_info["namespace"], "runtime")
        self.assertFalse(runtime_info["legacy"])
        self.assertFalse(runtime_info["deprecated"])

    def test_resolve_rpc_handler_maps_namespaced_and_legacy_methods(self):
        service = RuntimeService()

        self.assertEqual(resolve_rpc_handler(service, "runtime.info").__name__, "info")
        self.assertEqual(resolve_rpc_handler(service, "init").__name__, "init")
        self.assertEqual(
            resolve_rpc_handler(service, "dependency.status").__name__,
            "dependency_status",
        )
        self.assertEqual(resolve_rpc_handler(service, "model.list").__name__, "list_models")
        self.assertEqual(resolve_rpc_handler(service, "model.info").__name__, "model_info")
        self.assertEqual(
            resolve_rpc_handler(service, "agent.send_message_stream").__name__,
            "send_message_stream",
        )
        self.assertEqual(resolve_rpc_handler(service, "session.current").__name__, "current_session")
        self.assertEqual(resolve_rpc_handler(service, "session.delete").__name__, "delete_session")
        self.assertEqual(resolve_rpc_handler(service, "session.export").__name__, "export_session")
        self.assertEqual(resolve_rpc_handler(service, "session.rename").__name__, "rename_session")
        self.assertEqual(
            resolve_rpc_handler(service, "session.rollback").__name__,
            "rollback_session",
        )
        self.assertEqual(resolve_rpc_handler(service, "memory.list").__name__, "memory_list")
        self.assertEqual(resolve_rpc_handler(service, "memory.search").__name__, "memory_search")
        self.assertEqual(resolve_rpc_handler(service, "memory.graph").__name__, "memory_graph")

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

    def test_runtime_service_handle_returns_structured_error_response_by_default(self):
        service = RuntimeService()

        async def run():
            return await service.handle("not.registered", {})

        response = asyncio.run(run())

        self.assertFalse(response["ok"])
        self.assertEqual(response["error_code"], "method_not_found")
        self.assertIn("Unknown method", response["error"])
        self.assertEqual(response["error_object"]["code"], "method_not_found")
        self.assertEqual(response["error_object"]["details"]["method"], "not.registered")
        self.assertIn("user_message", response["error_object"])

    def test_dispatch_rpc_can_wrap_tool_execution_error_as_runtime_error_response(self):
        class ToolFailingService:
            async def info(self):
                raise ToolExecutionError(
                    ToolError(
                        error_code="tool.test_failed",
                        technical_message="tool technical failure",
                        user_message="tool user failure",
                        recoverable=False,
                        details={"scope": "runtime"},
                    )
                )

        async def run():
            return await dispatch_rpc(ToolFailingService(), "runtime.info", {}, structured_errors=True)

        response = asyncio.run(run())

        self.assertFalse(response["ok"])
        self.assertEqual(response["error_code"], "tool.test_failed")
        self.assertEqual(response["error"], "tool technical failure")
        self.assertEqual(response["error_object"]["user_message"], "tool user failure")
        self.assertFalse(response["error_object"]["recoverable"])
        self.assertEqual(response["error_object"]["details"], {"scope": "runtime"})


class FakeWorkingMemory:
    def __init__(self, messages):
        self.messages = messages

    def get_context(self):
        return list(self.messages)


class FakeRuntimeSessionPersistence:
    def __init__(self, manager):
        self.manager = manager
        self.saved_sessions = []

    def load_messages(self, session_id):
        return list(self.manager.messages_by_session.get(session_id, []))

    def save_session(self, session):
        self.saved_sessions.append(session.session_id)


class FakeRuntimeSessionManager:
    def __init__(self):
        self.current = SessionContext(character_id="reimu", total_turns=1)
        self.sessions = {self.current.session_id: self.current}
        self.messages_by_session = {
            self.current.session_id: [
                {"role": "user", "content": "你好"},
                {"role": "assistant", "content": "你好呀"},
            ]
        }
        self.deleted = []
        self.saved = False
        self.persistence = FakeRuntimeSessionPersistence(self)

    def get_session(self, session_id):
        return self.sessions.get(session_id)

    def get_current_session(self):
        return self.current

    def list_sessions(self):
        return list(self.sessions.values())

    def get_working_memory(self, session_id=None):
        sid = session_id or (self.current.session_id if self.current else "")
        return FakeWorkingMemory(self.messages_by_session.get(sid, []))

    def delete_session(self, session_id):
        if session_id not in self.sessions:
            return False
        self.deleted.append(session_id)
        del self.sessions[session_id]
        self.messages_by_session.pop(session_id, None)
        if self.current and self.current.session_id == session_id:
            self.current = None
        return True

    def save_current(self):
        self.saved = True
        if self.current:
            messages = self.messages_by_session.get(self.current.session_id, [])
            self.current.total_turns = len(messages) // 2


class FakeRuntimeSemanticMemory:
    def __init__(self):
        self.item = {
            "id": "memory-1",
            "content": "灵梦喜欢喝茶",
            "importance": 0.8,
            "topic_name": "偏好",
            "diagnostics": {"embedding_used": False},
        }
        self.deleted = False

    def list_memories(self, **kwargs):
        return {"items": [self.item], "total": 1, "limit": kwargs.get("limit"), "offset": kwargs.get("offset")}

    async def search_async(self, **kwargs):
        return [{**self.item, "score": 0.9, "matched_by": ["memory_keyword"]}]

    def get_memory(self, memory_id):
        return self.item if memory_id == "memory-1" and not self.deleted else None

    async def update_memory(self, memory_id, **kwargs):
        if memory_id != "memory-1" or self.deleted:
            return None
        self.item = {**self.item, **{key: value for key, value in kwargs.items() if value is not None}}
        return self.item

    async def delete_memory(self, memory_id):
        if memory_id != "memory-1" or self.deleted:
            return False
        self.deleted = True
        return True

    def get_topic_graph(self):
        return {"nodes": [{"id": "topic-1", "recall_weight": 0.8}], "edges": []}


class RuntimeMemoryRpcTests(unittest.TestCase):
    def test_memory_rpc_methods_return_public_memory_payloads(self):
        service = RuntimeService()
        memory = FakeRuntimeSemanticMemory()
        cast(Any, service.state).agent = SimpleNamespace(semantic_memory=memory)

        async def run():
            listed = await service.handle("memory.list", {"limit": 10})
            searched = await service.handle("memory.search", {"query": "喝茶"})
            fetched = await service.handle("memory.get", {"memory_id": "memory-1"})
            updated = await service.handle("memory.update", {"memory_id": "memory-1", "importance": 0.9})
            graph = await service.handle("memory.graph")
            deleted = await service.handle("memory.delete", {"memory_id": "memory-1"})
            missing = await service.handle("memory.get", {"memory_id": "memory-1"})
            return listed, searched, fetched, updated, graph, deleted, missing

        listed, searched, fetched, updated, graph, deleted, missing = asyncio.run(run())

        self.assertEqual(listed["total"], 1)
        self.assertEqual(searched["items"][0]["score"], 0.9)
        self.assertFalse(searched["diagnostics"]["embedding_used"])
        self.assertEqual(fetched["id"], "memory-1")
        self.assertTrue(updated["updated"])
        self.assertEqual(updated["memory"]["importance"], 0.9)
        self.assertEqual(graph["topic_count"], 1)
        self.assertTrue(deleted["deleted"])
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error_code"], "runtime.error")

    def test_memory_rpc_requires_initialized_agent(self):
        service = RuntimeService()

        response = asyncio.run(service.handle("memory.list"))

        self.assertFalse(response["ok"])
        self.assertEqual(response["error_code"], "runtime.error")
        self.assertIn("Runtime is not initialized", response["error"])


class RuntimeSessionRpcTests(unittest.TestCase):
    def test_current_and_delete_session_return_json_compatible_payloads(self):
        service = RuntimeService()
        manager = FakeRuntimeSessionManager()
        cast(Any, service.state).agent = SimpleNamespace(session_manager=manager)
        assert manager.current is not None
        session_id = manager.current.session_id

        async def run():
            current = await service.handle("session.current")
            deleted = await service.handle("session.delete", {"session_id": session_id})
            missing = await service.handle("session.delete", {"session_id": session_id})
            return current, deleted, missing

        current, deleted, missing = asyncio.run(run())

        self.assertEqual(current["session_id"], session_id)
        self.assertTrue(deleted["deleted"])
        self.assertTrue(deleted["was_current"])
        self.assertIsNone(deleted["current_session"])
        self.assertEqual(deleted["remaining_count"], 0)
        self.assertEqual(deleted["remaining_sessions"], [])
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error_code"], "runtime.error")

    def test_export_session_returns_complete_machine_readable_payload(self):
        service = RuntimeService()
        manager = FakeRuntimeSessionManager()
        cast(Any, service.state).agent = SimpleNamespace(
            session_manager=manager,
            config=SimpleNamespace(character=SimpleNamespace(name="博丽灵梦")),
        )
        assert manager.current is not None
        session_id = manager.current.session_id

        async def run():
            exported = await service.handle("session.export")
            missing = await service.handle("session.export", {"session_id": "missing"})
            return exported, missing

        exported, missing = asyncio.run(run())

        self.assertEqual(exported["format"], "gensokyoai.session.export")
        self.assertEqual(exported["version"], 1)
        self.assertTrue(exported["is_current"])
        self.assertEqual(exported["character"]["name"], "博丽灵梦")
        self.assertEqual(exported["session"]["session_id"], session_id)
        self.assertEqual(exported["message_count"], 2)
        self.assertEqual(exported["messages"][0]["content"], "你好")
        self.assertIn("runtime", exported)
        self.assertTrue(manager.saved)
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error_code"], "runtime.error")

    def test_rename_session_stores_title_in_metadata(self):
        service = RuntimeService()
        manager = FakeRuntimeSessionManager()
        cast(Any, service.state).agent = SimpleNamespace(session_manager=manager)
        assert manager.current is not None
        session_id = manager.current.session_id

        async def run():
            renamed = await service.handle("session.rename", {"title": " 新标题 "})
            invalid = await service.handle("session.rename", {"title": "   "})
            return renamed, invalid

        renamed, invalid = asyncio.run(run())

        self.assertEqual(renamed["session_id"], session_id)
        self.assertEqual(renamed["metadata"]["title"], "新标题")
        self.assertIn(session_id, manager.persistence.saved_sessions)
        self.assertFalse(invalid["ok"])
        self.assertEqual(invalid["error_code"], "runtime.error")

    def test_rollback_session_validates_mode_and_saves_current_memory(self):
        service = RuntimeService()
        manager = FakeRuntimeSessionManager()
        rollback_calls = []

        def rollback(num=1, mode="turns"):
            rollback_calls.append((num, mode))
            assert manager.current is not None
            manager.messages_by_session[manager.current.session_id] = []

        cast(Any, service.state).agent = SimpleNamespace(
            session_manager=manager,
            rollback=rollback,
        )

        async def run():
            rolled_back = await service.handle(
                "session.rollback",
                {"num": 2, "mode": "messages"},
            )
            invalid = await service.handle("session.rollback", {"num": 0})
            return rolled_back, invalid

        rolled_back, invalid = asyncio.run(run())

        self.assertTrue(rolled_back["rolled_back"])
        self.assertEqual(rolled_back["num"], 2)
        self.assertEqual(rolled_back["mode"], "messages")
        self.assertEqual(rolled_back["before_total_turns"], 1)
        self.assertEqual(rolled_back["after_total_turns"], 0)
        self.assertEqual(rolled_back["before_message_count"], 2)
        self.assertEqual(rolled_back["after_message_count"], 0)
        self.assertEqual(rolled_back["message_count"], 0)
        self.assertEqual(rollback_calls, [(2, "messages")])
        self.assertTrue(manager.saved)
        self.assertFalse(invalid["ok"])
        self.assertEqual(invalid["error_code"], "runtime.error")


class RuntimeStreamingRpcTests(unittest.TestCase):
    def test_send_message_stream_returns_stable_event_list_and_finish_event(self):
        service = RuntimeService()
        manager = FakeRuntimeSessionManager()
        start_calls = []

        async def start():
            start_calls.append(True)

        async def send_stream(message, system_contexts=None):
            yield StreamChunk(content="你")
            yield StreamChunk(content="好", status="streaming")

        cast(Any, service.state).agent = SimpleNamespace(
            start=start,
            send_stream=send_stream,
            session_manager=manager,
        )
        service.state.started = False

        async def run():
            return await service.handle(
                "agent.send_message_stream",
                {"message": "hi", "system_contexts": ["ctx"]},
            )

        result = asyncio.run(run())

        self.assertEqual(start_calls, [True])
        self.assertEqual(result["role"], "assistant")
        self.assertEqual(result["content"], "你好")
        self.assertEqual(result["events"][0], {"type": "content", "index": 0, "content": "你"})
        self.assertEqual(result["events"][1]["type"], "content")
        self.assertEqual(result["events"][1]["status"], "streaming")
        self.assertEqual(result["events"][-1]["type"], "finish")
        self.assertEqual(result["events"][-1]["content"], "你好")
        assert manager.current is not None
        self.assertEqual(result["session"]["session_id"], manager.current.session_id)


class RuntimeEventSubscriptionTests(unittest.TestCase):
    def test_runtime_event_payload_redacts_sensitive_fields_recursively(self):
        event = Event(
            type=SystemEvent.MODEL_AUTH,
            source="test",
            data={
                "api_key": "sk-secret",
                "Authorization": "Bearer token",
                "nested": {
                    "refresh_token": "refresh-secret",
                    "safe": "visible",
                },
                "items": [{"password": "pw", "value": 1}],
            },
            metadata={"headers": {"X-Test": "1"}, "safe_meta": "ok"},
        )

        payload = RuntimeService._runtime_event_payload(event)

        self.assertEqual(payload["data"]["api_key"], "[redacted]")
        self.assertEqual(payload["data"]["Authorization"], "[redacted]")
        self.assertEqual(payload["data"]["nested"]["refresh_token"], "[redacted]")
        self.assertEqual(payload["data"]["nested"]["safe"], "visible")
        self.assertEqual(payload["data"]["items"][0]["password"], "[redacted]")
        self.assertEqual(payload["data"]["items"][0]["value"], 1)
        self.assertEqual(payload["metadata"]["headers"], "[redacted]")
        self.assertEqual(payload["metadata"]["safe_meta"], "ok")

    def test_event_subscription_reports_backpressure_when_queue_is_full(self):
        service = RuntimeService()
        event_bus = EventBus(enable_trace=False)
        agent = SimpleNamespace(event_bus=event_bus)
        cast(Any, service.state).agent = agent

        async def run():
            subscription = await service.create_event_subscription(
                event_types=["tool.call.started"],
                queue_size=1,
            )
            queue = subscription["queue"]
            await event_bus._process_event(
                Event(
                    type=SystemEvent.TOOL_CALL_STARTED,
                    source="test",
                    data={"name": "first"},
                )
            )
            await event_bus._process_event(
                Event(
                    type=SystemEvent.TOOL_CALL_STARTED,
                    source="test",
                    data={"name": "second", "api_key": "secret"},
                )
            )
            payload = queue.get_nowait()
            queue.task_done()
            await service.close_event_subscription(subscription["subscription_id"])
            return payload

        payload = asyncio.run(run())

        self.assertEqual(payload["type"], "runtime.backpressure.dropped")
        self.assertEqual(payload["data"]["dropped_count"], 1)
        self.assertEqual(payload["data"]["queue_size"], 1)
        self.assertEqual(payload["data"]["dropped_event_type"], "tool.call.started")
        self.assertNotIn("api_key", payload["data"])
        self.assertEqual(event_bus.stats["subscriber_count"], 0)


class ConfigValidationAndRuntimePathTests(unittest.TestCase):
    def test_config_loader_rejects_unknown_fields_and_invalid_ranges(self):
        with self.assertRaisesRegex(ValueError, "Unknown config fields in model"):
            ConfigLoader()._dict_to_config({"model": {"unknown": True}})
        with self.assertRaisesRegex(ValueError, "model.temperature"):
            ConfigLoader()._dict_to_config({"model": {"temperature": 9}})
        with self.assertRaisesRegex(ValueError, "tool.web_search.max_results"):
            ConfigLoader()._dict_to_config({"tool": {"web_search": {"max_results": 0}}})

    def test_runtime_resolve_optional_rejects_paths_outside_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = RuntimeService(root_dir=root)
            inside = service._resolve_optional("config/default.yaml")
            self.assertIsNotNone(inside)
            assert inside is not None
            self.assertTrue(inside.is_relative_to(root.resolve()))
            with self.assertRaisesRegex(ValueError, "outside Runtime root"):
                service._resolve_optional(str(root.parent / "secret.yaml"))

    def test_config_loader_load_reports_friendly_validation_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.yaml"
            path.write_text(yaml.safe_dump({"model": {"timeout": 0}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "model.timeout"):
                ConfigLoader().load(path)


class EventBusP0Tests(unittest.TestCase):
    def test_event_bus_backpressure_stats_and_critical_flush(self):
        delivered = []

        async def handler(event):
            delivered.append(event.type)

        async def run():
            bus = EventBus(enable_trace=False, max_queue_size=1)
            bus.subscribe(SystemEvent.PERSISTENCE_SAVE_COMPLETED, handler)
            bus.publish(Event(type=SystemEvent.PERSISTENCE_SAVE_COMPLETED, source="test"))
            bus.publish(Event(type=SystemEvent.MODEL_COMPLETED, source="test"))
            await bus.flush_critical(timeout=0.1)
            return bus.stats

        stats = asyncio.run(run())

        self.assertEqual(delivered, [SystemEvent.PERSISTENCE_SAVE_COMPLETED])
        self.assertEqual(stats["dropped"], 1)
        self.assertEqual(stats["critical_flushed"], 1)
        self.assertEqual(stats["queue_max_size"], 1)


class RuntimeOverrideTests(unittest.TestCase):
    def test_model_overrides_allow_runtime_api_related_fields(self):
        config = ModelConfig(provider="openai", name="old")

        RuntimeService._apply_model_overrides(
            config,
            {
                "api_path": "/custom/chat/completions",
                "extra_headers": {"X-Test": "1"},
                "web_search_enabled": True,
                "web_search_strategy": "explicit",
                "retry_max_attempts": 5,
                "retry_initial_delay": 0.5,
                "retry_backoff_factor": 1.5,
                "retry_status_codes": [500, 502, 429],
                "not_allowed": "ignored",
            },
        )

        self.assertEqual(config.api_path, "/custom/chat/completions")
        self.assertEqual(config.extra_headers, {"X-Test": "1"})
        self.assertTrue(config.web_search_enabled)
        self.assertEqual(config.web_search_strategy, "explicit")
        self.assertEqual(config.retry_max_attempts, 5)
        self.assertEqual(config.retry_initial_delay, 0.5)
        self.assertEqual(config.retry_backoff_factor, 1.5)
        self.assertEqual(config.retry_status_codes, [500, 502, 429])
        self.assertFalse(hasattr(config, "not_allowed"))


if __name__ == "__main__":
    unittest.main()
