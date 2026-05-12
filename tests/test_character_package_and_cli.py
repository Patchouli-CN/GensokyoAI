import asyncio
import contextlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import yaml

from GensokyoAI.commands.character_cli import main as character_cli_main
from GensokyoAI.core.character_package import (
    CHARACTER_PACKAGE_MANIFEST,
    CharacterPackageService,
)
from GensokyoAI.runtime.rpc import rpc_methods
from GensokyoAI.runtime.service import RuntimeService

VALID_CHARACTER = {
    "name": "测试角色",
    "system_prompt": "你是测试角色。",
    "greeting": "你好。",
    "example_dialogue": [{"user": "你好", "assistant": "你好。"}],
    "metadata": {"locale": "zh_cn"},
}


class CharacterPackageServiceTests(unittest.TestCase):
    def test_export_validate_preview_and_import_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character_path = root / "reimu.yaml"
            package_path = root / "reimu.gensokyo-character"
            characters_dir = root / "characters"
            character_path.write_text(yaml.safe_dump(VALID_CHARACTER, allow_unicode=True), encoding="utf-8")

            service = CharacterPackageService()
            exported = service.export_package(
                character_path,
                package_path,
                package_id="reimu",
                author="tester",
            )
            validated = service.validate_package(package_path)
            preview = service.preview_package(package_path)
            imported = service.import_package(package_path, characters_dir)

            self.assertTrue(exported["ok"])
            self.assertTrue(validated["ok"])
            self.assertTrue(preview["ok"])
            self.assertEqual(preview["preview"]["name"], "测试角色")
            self.assertTrue(imported["imported"])
            self.assertTrue((characters_dir / "reimu.yaml").exists())

    def test_validate_rejects_unsafe_archive_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "bad.gensokyo-character"
            manifest = {
                "format": "gensokyoai.character.package",
                "schema_version": 1,
                "id": "bad",
                "name": "Bad",
                "version": "1.0.0",
                "character": "../bad.yaml",
            }
            with zipfile.ZipFile(package_path, "w") as archive:
                archive.writestr(CHARACTER_PACKAGE_MANIFEST, yaml.safe_dump(manifest))
                archive.writestr("../bad.yaml", yaml.safe_dump(VALID_CHARACTER))

            payload = CharacterPackageService().validate_package(package_path)

            self.assertFalse(payload["ok"])
            codes = {item["code"] for item in payload["diagnostics"]}
            self.assertIn("character_package.path.unsafe", codes)
            self.assertIn("character_package.manifest.character_unsafe", codes)

    def test_validate_requires_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "missing.gensokyo-character"
            with zipfile.ZipFile(package_path, "w") as archive:
                archive.writestr("character.yaml", yaml.safe_dump(VALID_CHARACTER))

            payload = CharacterPackageService().validate_package(package_path)

            self.assertFalse(payload["ok"])
            self.assertEqual(payload["diagnostics"][0]["code"], "character_package.manifest.missing")

    def test_import_rejects_duplicate_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character_path = root / "reimu.yaml"
            package_path = root / "reimu.gensokyo-character"
            characters_dir = root / "characters"
            characters_dir.mkdir()
            (characters_dir / "reimu.yaml").write_text("name: old\nsystem_prompt: old\n", encoding="utf-8")
            character_path.write_text(yaml.safe_dump(VALID_CHARACTER, allow_unicode=True), encoding="utf-8")
            service = CharacterPackageService()
            service.export_package(character_path, package_path, package_id="reimu")

            imported = service.import_package(package_path, characters_dir)

            self.assertFalse(imported["ok"])
            self.assertFalse(imported["imported"])
            self.assertIn("character_package.import.duplicate", {d["code"] for d in imported["diagnostics"]})


class CharacterCliTests(unittest.TestCase):
    def test_cli_file_returns_zero_for_valid_character(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.yaml"
            path.write_text(yaml.safe_dump(VALID_CHARACTER, allow_unicode=True), encoding="utf-8")

            exit_code = character_cli_main([str(path), "--json"])

            self.assertEqual(exit_code, 0)

    def test_cli_directory_returns_nonzero_when_file_has_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bad.yaml").write_text("name: ''\n", encoding="utf-8")

            exit_code = character_cli_main([str(root), "--json"])

            self.assertEqual(exit_code, 1)

    def test_cli_json_output_is_machine_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.yaml"
            path.write_text(yaml.safe_dump(VALID_CHARACTER, allow_unicode=True), encoding="utf-8")
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                exit_code = character_cli_main([str(path), "--json"])

            payload = json.loads(stream.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["preview"]["name"], "测试角色")


class CharacterPackageRuntimeTests(unittest.TestCase):
    def test_rpc_methods_include_character_package_methods(self):
        methods = rpc_methods()

        self.assertIn("character_package.validate", methods)
        self.assertIn("character_package.preview", methods)
        self.assertIn("character_package.import", methods)
        self.assertIn("character_package.export", methods)

    def test_runtime_info_includes_character_package_capability(self):
        payload = asyncio.run(RuntimeService(Path.cwd()).info())

        self.assertIn("character_package.management", payload["capabilities"])
        self.assertEqual(payload["schema_versions"]["character_package"], 1)


if __name__ == "__main__":
    unittest.main()
