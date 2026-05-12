"""角色包导入、导出、预览与校验工具。"""

from __future__ import annotations

import shutil
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .character_validator import CharacterValidator
from .config_validator import ConfigDiagnostic
from .schema_versions import CHARACTER_PACKAGE_FORMAT, CHARACTER_PACKAGE_SCHEMA_VERSION

CHARACTER_PACKAGE_EXTENSION = ".gensokyo-character"
CHARACTER_PACKAGE_MANIFEST = "manifest.yaml"
DEFAULT_CHARACTER_ENTRY = "character.yaml"
MAX_CHARACTER_PACKAGE_BYTES = 20 * 1024 * 1024
MAX_CHARACTER_PACKAGE_FILE_BYTES = 8 * 1024 * 1024
ALLOWED_RESOURCE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".txt",
    ".md",
    ".json",
    ".yaml",
    ".yml",
}


@dataclass(frozen=True, slots=True)
class CharacterPackageOptions:
    """角色包安全限制。"""

    max_package_bytes: int = MAX_CHARACTER_PACKAGE_BYTES
    max_file_bytes: int = MAX_CHARACTER_PACKAGE_FILE_BYTES


class CharacterPackageService:
    """角色包校验、导入和导出服务。"""

    MANIFEST_REQUIRED_FIELDS = {"id", "name", "version", "character"}
    MANIFEST_ALLOWED_FIELDS = {
        "format",
        "schema_version",
        "id",
        "name",
        "version",
        "author",
        "license",
        "description",
        "gensokyoai_version",
        "compatible_gensokyoai_versions",
        "character",
        "assets",
        "recommended_config",
        "memory_seeds",
        "metadata",
        "created_at",
    }

    def __init__(self, options: CharacterPackageOptions | None = None) -> None:
        self.options = options or CharacterPackageOptions()
        self._character_validator = CharacterValidator()

    def validate_package(self, package_path: Path) -> dict[str, Any]:
        """校验角色包并返回结构化 payload。"""

        return self._package_payload(package_path, include_files=True)

    def preview_package(self, package_path: Path) -> dict[str, Any]:
        """返回角色包预览。"""

        return self._package_payload(package_path, include_files=True)

    def export_package(
        self,
        character_path: Path,
        output_path: Path,
        *,
        package_id: str | None = None,
        author: str | None = None,
        license: str | None = None,
        assets: list[Path] | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """从角色 YAML 和可选资源导出角色包。"""

        diagnostics: list[ConfigDiagnostic] = []
        character_path = character_path.resolve()
        output_path = self._normalize_package_output_path(output_path)
        if output_path.exists() and not overwrite:
            diagnostics.append(
                self._error(
                    "output_path",
                    f"Character package already exists: {output_path}",
                    "如需覆盖，请启用 overwrite。",
                    code="character_package.export.exists",
                )
            )
            return self._result_payload(False, diagnostics, package_path=output_path)

        character_data = self._load_yaml_file(character_path, diagnostics, "character")
        character_diagnostics = self._character_validator.validate_character_dict(character_data)
        diagnostics.extend(self._prefix_diagnostics(character_diagnostics, "character"))
        preview = self._character_validator.build_preview(
            character_data, fallback_id=character_path.stem
        )
        if any(item.severity == "error" for item in diagnostics):
            return self._result_payload(
                False, diagnostics, package_path=output_path, preview=preview
            )

        manifest = {
            "format": CHARACTER_PACKAGE_FORMAT,
            "schema_version": CHARACTER_PACKAGE_SCHEMA_VERSION,
            "id": package_id or character_path.stem,
            "name": character_data.get("name") or character_path.stem,
            "version": "1.0.0",
            "author": author,
            "license": license,
            "character": DEFAULT_CHARACTER_ENTRY,
            "assets": [],
            "metadata": {},
            "created_at": datetime.now(UTC).isoformat(),
        }
        asset_entries: list[tuple[Path, str]] = []
        for asset in assets or []:
            resolved_asset = asset.resolve()
            if not resolved_asset.exists() or not resolved_asset.is_file():
                diagnostics.append(
                    self._error(
                        "assets",
                        f"Asset does not exist or is not a file: {asset}",
                        "请确认资源路径存在。",
                        code="character_package.asset.missing",
                    )
                )
                continue
            if resolved_asset.suffix.lower() not in ALLOWED_RESOURCE_SUFFIXES:
                diagnostics.append(
                    self._error(
                        "assets",
                        f"Asset suffix is not allowed: {resolved_asset.name}",
                        "请仅打包图片、文本、JSON 或 YAML 资源。",
                        code="character_package.asset.suffix",
                    )
                )
                continue
            arcname = f"assets/{resolved_asset.name}"
            asset_entries.append((resolved_asset, arcname))
            manifest["assets"].append(arcname)

        if any(item.severity == "error" for item in diagnostics):
            return self._result_payload(
                False, diagnostics, package_path=output_path, preview=preview
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                CHARACTER_PACKAGE_MANIFEST,
                yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
            )
            archive.write(character_path, DEFAULT_CHARACTER_ENTRY)
            for asset_path, arcname in asset_entries:
                archive.write(asset_path, arcname)

        return {
            **self._result_payload(True, diagnostics, package_path=output_path, preview=preview),
            "manifest": self._manifest_summary(manifest),
            "written": True,
        }

    def import_package(
        self,
        package_path: Path,
        characters_dir: Path,
        *,
        locale: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """安全导入角色包到角色目录。"""

        payload = self._package_payload(package_path, include_files=True)
        diagnostics = [self._diagnostic_from_dict(item) for item in payload.get("diagnostics", [])]
        if not payload.get("ok"):
            return {**payload, "imported": False}

        manifest = payload.get("manifest", {})
        character_entry = manifest.get("character") or DEFAULT_CHARACTER_ENTRY
        character_id = str(manifest.get("id") or Path(character_entry).stem)
        target_dir = characters_dir / locale if locale else characters_dir
        target_path = target_dir / f"{character_id}.yaml"
        if target_path.exists() and not overwrite:
            diagnostics.append(
                self._error(
                    "id",
                    f"Character already exists: {target_path.name}",
                    "请更换角色 ID，或启用 overwrite 覆盖。",
                    code="character_package.import.duplicate",
                )
            )
            return {
                **payload,
                "ok": False,
                "imported": False,
                "target_path": str(target_path),
                "diagnostics": [item.to_dict() for item in diagnostics],
                "error_count": len([item for item in diagnostics if item.severity == "error"]),
                "warning_count": len([item for item in diagnostics if item.severity == "warning"]),
            }

        with zipfile.ZipFile(package_path) as archive:
            target_dir.mkdir(parents=True, exist_ok=True)
            with archive.open(character_entry) as source, open(target_path, "wb") as target:
                shutil.copyfileobj(source, target)
            assets_dir = target_dir / f"{character_id}_assets"
            for asset in manifest.get("assets", []) or []:
                asset_path = self._safe_archive_name(str(asset))
                if asset_path not in archive.namelist():
                    continue
                destination = assets_dir / Path(asset_path).name
                assets_dir.mkdir(parents=True, exist_ok=True)
                with archive.open(asset_path) as source, open(destination, "wb") as target:
                    shutil.copyfileobj(source, target)

        return {
            **payload,
            "imported": True,
            "target_path": str(target_path),
            "overwrite": overwrite,
        }

    def _package_payload(self, package_path: Path, *, include_files: bool) -> dict[str, Any]:
        diagnostics: list[ConfigDiagnostic] = []
        package_path = package_path.resolve()
        self._validate_package_path(package_path, diagnostics)
        manifest: dict[str, Any] = {}
        preview: dict[str, Any] | None = None
        files: list[dict[str, Any]] = []

        if not any(item.severity == "error" for item in diagnostics):
            try:
                with zipfile.ZipFile(package_path) as archive:
                    names = archive.namelist()
                    if CHARACTER_PACKAGE_MANIFEST not in names:
                        diagnostics.append(
                            self._error(
                                CHARACTER_PACKAGE_MANIFEST,
                                "Character package manifest is missing",
                                "请在包根目录提供 manifest.yaml。",
                                code="character_package.manifest.missing",
                            )
                        )
                    self._validate_archive_entries(archive, diagnostics)
                    if CHARACTER_PACKAGE_MANIFEST in names:
                        manifest = self._load_manifest(archive, diagnostics)
                        self._validate_manifest(manifest, diagnostics)
                    character_entry = (
                        manifest.get("character") if isinstance(manifest, dict) else None
                    )
                    if isinstance(character_entry, str) and character_entry in names:
                        with archive.open(character_entry) as file:
                            character_data = yaml.safe_load(file) or {}
                        character_diagnostics = self._character_validator.validate_character_dict(
                            character_data
                        )
                        diagnostics.extend(
                            self._prefix_diagnostics(character_diagnostics, "character")
                        )
                        preview = self._character_validator.build_preview(
                            character_data,
                            fallback_id=str(manifest.get("id") or Path(character_entry).stem),
                        )
                    elif character_entry:
                        diagnostics.append(
                            self._error(
                                "character",
                                f"Character entry is missing: {character_entry}",
                                "请确认 manifest.character 指向包内角色 YAML。",
                                code="character_package.character.missing",
                            )
                        )
                    if include_files:
                        files = [
                            {"path": info.filename, "size": info.file_size}
                            for info in archive.infolist()
                            if not info.is_dir()
                        ]
            except zipfile.BadZipFile:
                diagnostics.append(
                    self._error(
                        "$",
                        "Character package is not a valid zip archive",
                        "请确认文件是有效的 .gensokyo-character 包。",
                        code="character_package.zip.invalid",
                    )
                )
            except yaml.YAMLError as error:
                diagnostics.append(
                    self._error(
                        "$",
                        f"Character package YAML is invalid: {error}",
                        "请检查 manifest 或角色 YAML 格式。",
                        code="character_package.yaml.invalid",
                    )
                )

        errors = [item for item in diagnostics if item.severity == "error"]
        warnings = [item for item in diagnostics if item.severity == "warning"]
        return {
            "ok": not errors,
            "package_path": str(package_path),
            "format": CHARACTER_PACKAGE_FORMAT,
            "schema_version": CHARACTER_PACKAGE_SCHEMA_VERSION,
            "manifest": self._manifest_summary(manifest),
            "preview": preview,
            "files": files,
            "diagnostics": [item.to_dict() for item in diagnostics],
            "error_count": len(errors),
            "warning_count": len(warnings),
        }

    def _validate_package_path(
        self, package_path: Path, diagnostics: list[ConfigDiagnostic]
    ) -> None:
        if package_path.suffix != CHARACTER_PACKAGE_EXTENSION:
            diagnostics.append(
                self._error(
                    "package_path",
                    f"Character package extension must be {CHARACTER_PACKAGE_EXTENSION}",
                    "请使用 .gensokyo-character 文件扩展名。",
                    code="character_package.extension.invalid",
                )
            )
        if not package_path.exists() or not package_path.is_file():
            diagnostics.append(
                self._error(
                    "package_path",
                    f"Character package does not exist: {package_path}",
                    "请确认角色包路径存在。",
                    code="character_package.file.missing",
                )
            )
            return
        if package_path.stat().st_size > self.options.max_package_bytes:
            diagnostics.append(
                self._error(
                    "package_path",
                    "Character package is too large",
                    "请缩小角色包体积。",
                    code="character_package.size.limit",
                )
            )

    def _validate_archive_entries(
        self, archive: zipfile.ZipFile, diagnostics: list[ConfigDiagnostic]
    ) -> None:
        seen: set[str] = set()
        for info in archive.infolist():
            name = info.filename
            try:
                safe_name = self._safe_archive_name(name)
            except ValueError:
                diagnostics.append(
                    self._error(
                        name,
                        "Archive entry path is unsafe",
                        "包内路径不能使用绝对路径或 .. 穿越。",
                        code="character_package.path.unsafe",
                    )
                )
                continue
            if safe_name in seen:
                diagnostics.append(
                    self._error(
                        safe_name,
                        "Duplicate archive entry",
                        "请移除重复文件。",
                        code="character_package.path.duplicate",
                    )
                )
            seen.add(safe_name)
            if info.file_size > self.options.max_file_bytes:
                diagnostics.append(
                    self._error(
                        safe_name,
                        "Archive entry is too large",
                        "请缩小单个资源文件体积。",
                        code="character_package.file.size_limit",
                    )
                )
            if not info.is_dir() and safe_name != CHARACTER_PACKAGE_MANIFEST:
                suffix = Path(safe_name).suffix.lower()
                if suffix and suffix not in ALLOWED_RESOURCE_SUFFIXES:
                    diagnostics.append(
                        self._warning(
                            safe_name,
                            "Archive entry suffix is unusual",
                            "请确认包内仅包含角色 YAML、图片和文本类资源。",
                            code="character_package.file.suffix_warning",
                        )
                    )

    def _load_manifest(
        self, archive: zipfile.ZipFile, diagnostics: list[ConfigDiagnostic]
    ) -> dict[str, Any]:
        with archive.open(CHARACTER_PACKAGE_MANIFEST) as file:
            data = yaml.safe_load(file) or {}
        if not isinstance(data, dict):
            diagnostics.append(
                self._error(
                    CHARACTER_PACKAGE_MANIFEST,
                    "Character package manifest must be an object",
                    "请将 manifest.yaml 写成 key/value 对象。",
                    code="character_package.manifest.type",
                )
            )
            return {}
        return data

    def _validate_manifest(
        self, manifest: dict[str, Any], diagnostics: list[ConfigDiagnostic]
    ) -> None:
        for field_name in sorted(set(manifest) - self.MANIFEST_ALLOWED_FIELDS):
            diagnostics.append(
                self._warning(
                    field_name,
                    f"Unknown manifest field '{field_name}'",
                    "当前版本会忽略未知 manifest 字段。",
                    code="character_package.manifest.field_unknown",
                )
            )
        for field_name in sorted(self.MANIFEST_REQUIRED_FIELDS - set(manifest)):
            diagnostics.append(
                self._error(
                    field_name,
                    f"Required manifest field '{field_name}' is missing",
                    "请补充角色包 ID、名称、版本和 character 入口。",
                    code="character_package.manifest.field_required",
                )
            )
        if manifest.get("format") not in (None, CHARACTER_PACKAGE_FORMAT):
            diagnostics.append(
                self._error(
                    "format",
                    "Character package format is not supported",
                    "请使用当前版本支持的角色包格式。",
                    code="character_package.format.unsupported",
                )
            )
        schema_version = manifest.get("schema_version")
        if schema_version not in (None, CHARACTER_PACKAGE_SCHEMA_VERSION):
            diagnostics.append(
                self._error(
                    "schema_version",
                    "Character package schema version is not supported",
                    "请升级 GensokyoAI 或重新导出角色包。",
                    code="character_package.schema.unsupported",
                )
            )
        for field_name in ("id", "name", "version", "character"):
            value = manifest.get(field_name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                diagnostics.append(
                    self._error(
                        field_name,
                        f"Manifest field '{field_name}' must be a non-empty string",
                        "请填写非空字符串。",
                        code="character_package.manifest.field_type",
                    )
                )
        character = manifest.get("character")
        if isinstance(character, str):
            try:
                self._safe_archive_name(character)
            except ValueError:
                diagnostics.append(
                    self._error(
                        "character",
                        "Manifest character path is unsafe",
                        "character 入口不能使用绝对路径或 .. 穿越。",
                        code="character_package.manifest.character_unsafe",
                    )
                )
        assets = manifest.get("assets")
        if assets is not None:
            if not isinstance(assets, list) or not all(isinstance(item, str) for item in assets):
                diagnostics.append(
                    self._error(
                        "assets",
                        "Manifest assets must be a list of strings",
                        "请将 assets 写成包内资源路径列表。",
                        code="character_package.manifest.assets_type",
                    )
                )
            else:
                for asset in assets:
                    try:
                        self._safe_archive_name(asset)
                    except ValueError:
                        diagnostics.append(
                            self._error(
                                "assets",
                                f"Manifest asset path is unsafe: {asset}",
                                "asset 路径不能使用绝对路径或 .. 穿越。",
                                code="character_package.manifest.asset_unsafe",
                            )
                        )

    @staticmethod
    def _safe_archive_name(name: str) -> str:
        normalized = name.replace("\\", "/").strip()
        path = Path(normalized)
        if not normalized or path.is_absolute() or any(part in {"..", ""} for part in path.parts):
            raise ValueError(name)
        return normalized

    @staticmethod
    def _normalize_package_output_path(output_path: Path) -> Path:
        if output_path.suffix != CHARACTER_PACKAGE_EXTENSION:
            output_path = output_path.with_suffix(CHARACTER_PACKAGE_EXTENSION)
        return output_path.resolve()

    @staticmethod
    def _load_yaml_file(path: Path, diagnostics: list[ConfigDiagnostic], prefix: str) -> Any:
        try:
            with open(path, encoding="utf-8") as file:
                return yaml.safe_load(file) or {}
        except yaml.YAMLError as error:
            diagnostics.append(
                ConfigDiagnostic(
                    code=f"{prefix}.yaml.invalid",
                    path=prefix,
                    severity="error",
                    message=f"YAML is invalid: {error}",
                    suggestion="请检查 YAML 缩进、冒号和列表格式。",
                )
            )
        except OSError as error:
            diagnostics.append(
                ConfigDiagnostic(
                    code=f"{prefix}.file.unreadable",
                    path=prefix,
                    severity="error",
                    message=str(error),
                    suggestion="请确认文件存在且可读取。",
                )
            )
        return {}

    @staticmethod
    def _manifest_summary(manifest: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(manifest, dict):
            return {}
        keys = {
            "format",
            "schema_version",
            "id",
            "name",
            "version",
            "author",
            "license",
            "description",
            "gensokyoai_version",
            "compatible_gensokyoai_versions",
            "character",
            "assets",
            "recommended_config",
            "memory_seeds",
            "metadata",
            "created_at",
        }
        return {key: manifest.get(key) for key in keys if key in manifest}

    @staticmethod
    def _result_payload(
        ok: bool,
        diagnostics: list[ConfigDiagnostic],
        *,
        package_path: Path,
        preview: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        errors = [item for item in diagnostics if item.severity == "error"]
        warnings = [item for item in diagnostics if item.severity == "warning"]
        return {
            "ok": ok and not errors,
            "package_path": str(package_path),
            "format": CHARACTER_PACKAGE_FORMAT,
            "schema_version": CHARACTER_PACKAGE_SCHEMA_VERSION,
            "preview": preview,
            "diagnostics": [item.to_dict() for item in diagnostics],
            "error_count": len(errors),
            "warning_count": len(warnings),
        }

    @staticmethod
    def _prefix_diagnostics(
        diagnostics: list[ConfigDiagnostic], prefix: str
    ) -> list[ConfigDiagnostic]:
        return [
            ConfigDiagnostic(
                code=item.code,
                path=f"{prefix}.{item.path}" if item.path != "$" else prefix,
                severity=item.severity,
                message=item.message,
                suggestion=item.suggestion,
            )
            for item in diagnostics
        ]

    @staticmethod
    def _diagnostic_from_dict(data: dict[str, Any]) -> ConfigDiagnostic:
        return ConfigDiagnostic(
            code=str(data.get("code") or "character_package.validation"),
            path=str(data.get("path") or "$"),
            severity="warning" if data.get("severity") == "warning" else "error",
            message=str(data.get("message") or "Character package validation failed"),
            suggestion=data.get("suggestion"),
        )

    @staticmethod
    def _error(
        path: str,
        message: str,
        suggestion: str | None = None,
        *,
        code: str = "character_package.validation.error",
    ) -> ConfigDiagnostic:
        return ConfigDiagnostic(
            code=code,
            path=path,
            severity="error",
            message=message,
            suggestion=suggestion,
        )

    @staticmethod
    def _warning(
        path: str,
        message: str,
        suggestion: str | None = None,
        *,
        code: str = "character_package.validation.warning",
    ) -> ConfigDiagnostic:
        return ConfigDiagnostic(
            code=code,
            path=path,
            severity="warning",
            message=message,
            suggestion=suggestion,
        )
