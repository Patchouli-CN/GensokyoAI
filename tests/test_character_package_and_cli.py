import asyncio
import contextlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import yaml

from GensokyoAI.cli.character_cli import main as character_cli_main
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
            character_path.write_text(
                yaml.safe_dump(VALID_CHARACTER, allow_unicode=True), encoding="utf-8"
            )

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
            self.assertIn("checksums", exported["manifest"])
            self.assertTrue(exported["trust"]["author_declared"])
            self.assertTrue(exported["security"]["checksums_valid"])
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
            self.assertEqual(
                payload["diagnostics"][0]["code"], "character_package.manifest.missing"
            )

    def test_import_rejects_duplicate_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character_path = root / "reimu.yaml"
            package_path = root / "reimu.gensokyo-character"
            characters_dir = root / "characters"
            characters_dir.mkdir()
            (characters_dir / "reimu.yaml").write_text(
                "name: old\nsystem_prompt: old\n", encoding="utf-8"
            )
            character_path.write_text(
                yaml.safe_dump(VALID_CHARACTER, allow_unicode=True), encoding="utf-8"
            )
            service = CharacterPackageService()
            service.export_package(character_path, package_path, package_id="reimu")

            imported = service.import_package(package_path, characters_dir)

            self.assertFalse(imported["ok"])
            self.assertFalse(imported["imported"])
            self.assertIn(
                "character_package.import.duplicate", {d["code"] for d in imported["diagnostics"]}
            )


    def test_validate_warns_for_missing_ecosystem_trust_metadata_on_legacy_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "legacy.gensokyo-character"
            manifest = {
                "format": "gensokyoai.character.package",
                "schema_version": 1,
                "id": "legacy",
                "name": "Legacy",
                "version": "1.0.0",
                "character": "character.yaml",
            }
            with zipfile.ZipFile(package_path, "w") as archive:
                archive.writestr(CHARACTER_PACKAGE_MANIFEST, yaml.safe_dump(manifest))
                archive.writestr("character.yaml", yaml.safe_dump(VALID_CHARACTER))

            payload = CharacterPackageService().validate_package(package_path)
            codes = {item["code"] for item in payload["diagnostics"]}

            self.assertTrue(payload["ok"])
            self.assertIn("character_package.trust.author_missing", codes)
            self.assertIn("character_package.trust.license_missing", codes)
            self.assertIn("character_package.trust.source_missing", codes)
            self.assertIn("character_package.trust.signature_missing", codes)
            self.assertIn("character_package.trust.checksums_missing", codes)
            self.assertFalse(payload["trust"]["author_declared"])
            self.assertFalse(payload["trust"]["checksums_declared"])

    def test_validate_rejects_insecure_external_link_and_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "unsafe.gensokyo-character"
            manifest = {
                "format": "gensokyoai.character.package",
                "schema_version": 1,
                "id": "unsafe",
                "name": "Unsafe",
                "version": "1.0.0",
                "author": "tester",
                "license": "MIT",
                "source": "http://example.com/unsafe",
                "character": "character.yaml",
                "external_links": [{"label": "bad", "url": "file:///tmp/bad"}],
                "checksums": {"sha256": {"character.yaml": "0" * 64}},
            }
            with zipfile.ZipFile(package_path, "w") as archive:
                archive.writestr(CHARACTER_PACKAGE_MANIFEST, yaml.safe_dump(manifest))
                archive.writestr("character.yaml", yaml.safe_dump(VALID_CHARACTER))

            payload = CharacterPackageService().validate_package(package_path)
            codes = {item["code"] for item in payload["diagnostics"]}

            self.assertFalse(payload["ok"])
            self.assertIn("character_package.external_link.scheme", codes)
            self.assertIn("character_package.checksums.mismatch", codes)
            self.assertFalse(payload["security"]["https_external_links_only"])
            self.assertFalse(payload["security"]["checksums_valid"])

    def test_validate_rejects_missing_declared_asset_and_warns_undeclared_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "assets.gensokyo-character"
            manifest = {
                "format": "gensokyoai.character.package",
                "schema_version": 1,
                "id": "assets",
                "name": "Assets",
                "version": "1.0.0",
                "author": "tester",
                "license": "MIT",
                "source": "https://example.com/assets",
                "character": "character.yaml",
                "assets": ["assets/missing.png"],
                "checksums": {"sha256": {}},
            }
            with zipfile.ZipFile(package_path, "w") as archive:
                archive.writestr(CHARACTER_PACKAGE_MANIFEST, yaml.safe_dump(manifest))
                archive.writestr("character.yaml", yaml.safe_dump(VALID_CHARACTER))
                archive.writestr("assets/extra.txt", "extra")

            payload = CharacterPackageService().validate_package(package_path)
            codes = {item["code"] for item in payload["diagnostics"]}

            self.assertFalse(payload["ok"])
            self.assertIn("character_package.manifest.asset_missing", codes)
            self.assertIn("character_package.security.undeclared_file", codes)
            self.assertTrue(payload["security"]["has_undeclared_files"])

    def test_export_accepts_ecosystem_metadata_from_runtime_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            character_path = root / "reimu.yaml"
            package_path = root / "reimu.gensokyo-character"
            character_path.write_text(
                yaml.safe_dump(VALID_CHARACTER, allow_unicode=True), encoding="utf-8"
            )
            service = RuntimeService(root)

            exported = asyncio.run(
                service.export_character_package(
                    str(character_path),
                    str(package_path),
                    package_id="reimu",
                    author="tester",
                    license="MIT",
                    source="https://example.com/reimu",
                    external_links=[{"label": "home", "url": "https://example.com/reimu"}],
                    repository={"id": "repo/reimu", "url": "https://example.com/index.json"},
                    signature={"algorithm": "ed25519", "value": "abcdEFGH12345678"},
                    overwrite=True,
                )
            )

            self.assertTrue(exported["ok"])
            self.assertTrue(exported["trust"]["source_declared"])
            self.assertEqual(exported["trust"]["external_link_count"], 1)
            self.assertIn("checksums", exported["manifest"])


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
