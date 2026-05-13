"""角色包导入、导出、预览与校验工具。"""

from __future__ import annotations

import hashlib
import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
ALLOWED_EXTERNAL_URL_SCHEMES = {"https"}
ALLOWED_SIGNATURE_ALGORITHMS = {"ed25519", "rsa-pss-sha256", "minisign"}
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
SIGNATURE_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9+/=_:.-]{16,4096}$")


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
        "author_url",
        "license",
        "license_url",
        "license_detail",
        "description",
        "source",
        "attribution",
        "external_links",
        "repository",
        "signature",
        "checksums",
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
        source: str | None = None,
        author_url: str | None = None,
        license_url: str | None = None,
        license_detail: str | None = None,
        attribution: list[dict[str, Any]] | None = None,
        external_links: list[dict[str, Any]] | None = None,
        repository: dict[str, Any] | None = None,
        signature: dict[str, Any] | None = None,
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

        manifest: dict[str, Any] = {
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
        optional_fields = {
            "source": source,
            "author_url": author_url,
            "license_url": license_url,
            "license_detail": license_detail,
            "attribution": attribution,
            "external_links": external_links,
            "repository": repository,
            "signature": signature,
        }
        for field_name, value in optional_fields.items():
            if value not in (None, [], {}):
                manifest[field_name] = value

        checksums: dict[str, str] = {}
        asset_entries: list[tuple[Path, str]] = []
        if character_path.exists() and character_path.is_file():
            checksums[DEFAULT_CHARACTER_ENTRY] = self._sha256_file(character_path)
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
            checksums[arcname] = self._sha256_file(resolved_asset)
        manifest["checksums"] = {"sha256": checksums}

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
            "trust": self._trust_summary(manifest),
            "security": self._security_summary(manifest, diagnostics),
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
            with archive.open(character_entry) as source_file, open(target_path, "wb") as target:
                shutil.copyfileobj(source_file, target)
            assets_dir = target_dir / f"{character_id}_assets"
            for asset in manifest.get("assets", []) or []:
                asset_path = self._safe_archive_name(str(asset))
                if asset_path not in archive.namelist():
                    continue
                destination = assets_dir / Path(asset_path).name
                assets_dir.mkdir(parents=True, exist_ok=True)
                with archive.open(asset_path) as source_file, open(destination, "wb") as target:
                    shutil.copyfileobj(source_file, target)

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
                    safe_names = self._validate_archive_entries(archive, diagnostics)
                    if CHARACTER_PACKAGE_MANIFEST not in names:
                        diagnostics.append(
                            self._error(
                                CHARACTER_PACKAGE_MANIFEST,
                                "Character package manifest is missing",
                                "请在包根目录提供 manifest.yaml。",
                                code="character_package.manifest.missing",
                            )
                        )
                    if CHARACTER_PACKAGE_MANIFEST in names:
                        manifest = self._load_manifest(archive, diagnostics)
                        self._validate_manifest(manifest, diagnostics, archive, safe_names)
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
            "trust": self._trust_summary(manifest),
            "security": self._security_summary(manifest, diagnostics),
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
    ) -> set[str]:
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
        return seen

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
        self,
        manifest: dict[str, Any],
        diagnostics: list[ConfigDiagnostic],
        archive: zipfile.ZipFile,
        safe_names: set[str],
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
        for field_name in (
            "author",
            "license",
            "description",
            "source",
            "license_detail",
            "author_url",
            "license_url",
        ):
            value = manifest.get(field_name)
            if value is not None and not isinstance(value, str):
                diagnostics.append(
                    self._error(
                        field_name,
                        f"Manifest field '{field_name}' must be a string",
                        "请将该字段写成字符串。",
                        code="character_package.manifest.field_type",
                    )
                )
        if not manifest.get("author"):
            diagnostics.append(
                self._warning(
                    "author",
                    "Character package author is not declared",
                    "建议声明作者或维护者，方便用户判断来源。",
                    code="character_package.trust.author_missing",
                )
            )
        if not manifest.get("license"):
            diagnostics.append(
                self._warning(
                    "license",
                    "Character package license is not declared",
                    "建议声明许可证或使用范围，方便二次分发。",
                    code="character_package.trust.license_missing",
                )
            )
        if not manifest.get("source"):
            diagnostics.append(
                self._warning(
                    "source",
                    "Character package source is not declared",
                    "建议声明来源页面、仓库或发布渠道。",
                    code="character_package.trust.source_missing",
                )
            )
        for field_name in ("source", "author_url", "license_url"):
            value = manifest.get(field_name)
            if isinstance(value, str) and value.strip():
                self._validate_url(field_name, value, diagnostics)

        character = manifest.get("character")
        character_path: str | None = None
        if isinstance(character, str):
            try:
                character_path = self._safe_archive_name(character)
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
        asset_paths: set[str] = set()
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
                        asset_path = self._safe_archive_name(asset)
                        asset_paths.add(asset_path)
                        if asset_path not in safe_names:
                            diagnostics.append(
                                self._error(
                                    "assets",
                                    f"Manifest asset is missing from archive: {asset_path}",
                                    "请确认 assets 中声明的资源实际存在于包内。",
                                    code="character_package.manifest.asset_missing",
                                )
                            )
                    except ValueError:
                        diagnostics.append(
                            self._error(
                                "assets",
                                f"Manifest asset path is unsafe: {asset}",
                                "asset 路径不能使用绝对路径或 .. 穿越。",
                                code="character_package.manifest.asset_unsafe",
                            )
                        )
        declared_paths = {CHARACTER_PACKAGE_MANIFEST}
        if character_path:
            declared_paths.add(character_path)
        declared_paths.update(asset_paths)
        for safe_name in sorted(safe_names - declared_paths):
            diagnostics.append(
                self._warning(
                    safe_name,
                    "Archive entry is not declared in manifest",
                    "建议只包含 manifest、character 和 assets 声明的资源，避免用户安装未知文件。",
                    code="character_package.security.undeclared_file",
                )
            )
        self._validate_external_links(manifest.get("external_links"), diagnostics)
        self._validate_attribution(manifest.get("attribution"), diagnostics)
        self._validate_repository(manifest.get("repository"), diagnostics)
        self._validate_signature(manifest.get("signature"), diagnostics)
        self._validate_checksums(manifest.get("checksums"), archive, diagnostics)

    def _validate_url(
        self, path: str, value: str, diagnostics: list[ConfigDiagnostic]
    ) -> None:
        parsed = urlparse(value)
        if parsed.scheme not in ALLOWED_EXTERNAL_URL_SCHEMES or not parsed.netloc:
            diagnostics.append(
                self._error(
                    path,
                    f"External URL must use https: {value}",
                    "外部链接仅允许 https URL，避免 file/http/javascript 等风险来源。",
                    code="character_package.external_link.scheme",
                )
            )

    def _validate_external_links(
        self, value: Any, diagnostics: list[ConfigDiagnostic]
    ) -> None:
        if value is None:
            return
        if not isinstance(value, list):
            diagnostics.append(
                self._error(
                    "external_links",
                    "Manifest external_links must be a list",
                    "请将 external_links 写成对象列表。",
                    code="character_package.external_links.type",
                )
            )
            return
        for index, item in enumerate(value):
            path = f"external_links[{index}]"
            if not isinstance(item, dict):
                diagnostics.append(
                    self._error(
                        path,
                        "External link entry must be an object",
                        "每个外部链接应包含 label、url 和可选 purpose。",
                        code="character_package.external_links.item_type",
                    )
                )
                continue
            label = item.get("label")
            url = item.get("url")
            if not isinstance(label, str) or not label.strip():
                diagnostics.append(
                    self._error(
                        f"{path}.label",
                        "External link label must be a non-empty string",
                        "请为外部链接提供可读名称。",
                        code="character_package.external_links.label_type",
                    )
                )
            if not isinstance(url, str) or not url.strip():
                diagnostics.append(
                    self._error(
                        f"{path}.url",
                        "External link url must be a non-empty string",
                        "请为外部链接提供 https URL。",
                        code="character_package.external_links.url_type",
                    )
                )
            else:
                self._validate_url(f"{path}.url", url, diagnostics)
            purpose = item.get("purpose")
            if purpose is not None and not isinstance(purpose, str):
                diagnostics.append(
                    self._error(
                        f"{path}.purpose",
                        "External link purpose must be a string",
                        "请用字符串说明该链接用途。",
                        code="character_package.external_links.purpose_type",
                    )
                )

    def _validate_attribution(
        self, value: Any, diagnostics: list[ConfigDiagnostic]
    ) -> None:
        if value is None:
            return
        if not isinstance(value, list):
            diagnostics.append(
                self._error(
                    "attribution",
                    "Manifest attribution must be a list",
                    "请将引用来源写成对象列表。",
                    code="character_package.attribution.type",
                )
            )
            return
        for index, item in enumerate(value):
            path = f"attribution[{index}]"
            if not isinstance(item, dict):
                diagnostics.append(
                    self._error(
                        path,
                        "Attribution entry must be an object",
                        "每条引用来源应包含 title/source/license 等字段。",
                        code="character_package.attribution.item_type",
                    )
                )
                continue
            for field_name in ("title", "source", "license"):
                field_value = item.get(field_name)
                if field_value is not None and not isinstance(field_value, str):
                    diagnostics.append(
                        self._error(
                            f"{path}.{field_name}",
                            f"Attribution field '{field_name}' must be a string",
                            "引用来源字段请使用字符串。",
                            code="character_package.attribution.field_type",
                        )
                    )
            source = item.get("source")
            if isinstance(source, str) and source.startswith(("http://", "https://")):
                self._validate_url(f"{path}.source", source, diagnostics)

    def _validate_repository(self, value: Any, diagnostics: list[ConfigDiagnostic]) -> None:
        if value is None:
            return
        if not isinstance(value, dict):
            diagnostics.append(
                self._error(
                    "repository",
                    "Manifest repository must be an object",
                    "包仓库索引元数据请写成对象。",
                    code="character_package.repository.type",
                )
            )
            return
        for field_name in ("id", "namespace", "url", "homepage", "download_url"):
            field_value = value.get(field_name)
            if field_value is not None and not isinstance(field_value, str):
                diagnostics.append(
                    self._error(
                        f"repository.{field_name}",
                        f"Repository field '{field_name}' must be a string",
                        "仓库索引元数据字段请使用字符串。",
                        code="character_package.repository.field_type",
                    )
                )
        for field_name in ("url", "homepage", "download_url"):
            field_value = value.get(field_name)
            if isinstance(field_value, str) and field_value.strip():
                self._validate_url(f"repository.{field_name}", field_value, diagnostics)

    def _validate_signature(self, value: Any, diagnostics: list[ConfigDiagnostic]) -> None:
        if value is None:
            diagnostics.append(
                self._warning(
                    "signature",
                    "Character package signature is not provided",
                    "当前版本不强制验签，但建议仓库或分发方提供签名字段。",
                    code="character_package.trust.signature_missing",
                )
            )
            return
        if not isinstance(value, dict):
            diagnostics.append(
                self._error(
                    "signature",
                    "Manifest signature must be an object",
                    "signature 请写成包含 algorithm、value 和可选 signer 的对象。",
                    code="character_package.signature.type",
                )
            )
            return
        algorithm = value.get("algorithm")
        signature_value = value.get("value")
        if not isinstance(algorithm, str) or algorithm not in ALLOWED_SIGNATURE_ALGORITHMS:
            diagnostics.append(
                self._warning(
                    "signature.algorithm",
                    "Signature algorithm is not recognized",
                    "当前仅识别 ed25519、rsa-pss-sha256 或 minisign；本版本只校验字段格式，不做真实验签。",
                    code="character_package.signature.algorithm",
                )
            )
        if not isinstance(signature_value, str) or not SIGNATURE_VALUE_PATTERN.match(signature_value):
            diagnostics.append(
                self._warning(
                    "signature.value",
                    "Signature value format is unusual",
                    "请提供 base64、minisign 或类似文本签名；本版本只校验字段格式，不做真实验签。",
                    code="character_package.signature.value_format",
                )
            )
        signer = value.get("signer")
        if signer is not None and not isinstance(signer, str):
            diagnostics.append(
                self._error(
                    "signature.signer",
                    "Signature signer must be a string",
                    "签名者标识请写成字符串。",
                    code="character_package.signature.signer_type",
                )
            )

    def _validate_checksums(
        self,
        value: Any,
        archive: zipfile.ZipFile,
        diagnostics: list[ConfigDiagnostic],
    ) -> None:
        if value is None:
            diagnostics.append(
                self._warning(
                    "checksums",
                    "Character package checksums are not provided",
                    "建议提供 sha256 校验和，方便导入前发现分发过程中的文件变化。",
                    code="character_package.trust.checksums_missing",
                )
            )
            return
        if not isinstance(value, dict):
            diagnostics.append(
                self._error(
                    "checksums",
                    "Manifest checksums must be an object",
                    "请将 checksums 写成 {sha256: {path: hash}}。",
                    code="character_package.checksums.type",
                )
            )
            return
        sha256 = value.get("sha256")
        if not isinstance(sha256, dict):
            diagnostics.append(
                self._error(
                    "checksums.sha256",
                    "Manifest checksums.sha256 must be an object",
                    "请将 sha256 校验和写成路径到哈希值的映射。",
                    code="character_package.checksums.sha256_type",
                )
            )
            return
        names = set(archive.namelist())
        for path, expected in sha256.items():
            if not isinstance(path, str) or not isinstance(expected, str):
                diagnostics.append(
                    self._error(
                        "checksums.sha256",
                        "Checksum paths and values must be strings",
                        "校验和映射中的路径和值都应为字符串。",
                        code="character_package.checksums.entry_type",
                    )
                )
                continue
            try:
                safe_path = self._safe_archive_name(path)
            except ValueError:
                diagnostics.append(
                    self._error(
                        "checksums.sha256",
                        f"Checksum path is unsafe: {path}",
                        "校验和路径不能使用绝对路径或 .. 穿越。",
                        code="character_package.checksums.path_unsafe",
                    )
                )
                continue
            if safe_path == CHARACTER_PACKAGE_MANIFEST:
                diagnostics.append(
                    self._warning(
                        "checksums.sha256",
                        "Manifest checksum is ignored",
                        "manifest.yaml 包含 checksums 字段，当前不要求自校验。",
                        code="character_package.checksums.manifest_ignored",
                    )
                )
                continue
            if not SHA256_PATTERN.match(expected):
                diagnostics.append(
                    self._error(
                        "checksums.sha256",
                        f"Checksum is not a valid sha256 hex digest for {safe_path}",
                        "sha256 值应为 64 位十六进制字符串。",
                        code="character_package.checksums.value_format",
                    )
                )
                continue
            if safe_path not in names:
                diagnostics.append(
                    self._error(
                        "checksums.sha256",
                        f"Checksum target is missing from archive: {safe_path}",
                        "请确认校验和路径实际存在于包内。",
                        code="character_package.checksums.target_missing",
                    )
                )
                continue
            with archive.open(safe_path) as file:
                actual = hashlib.sha256(file.read()).hexdigest()
            if actual.lower() != expected.lower():
                diagnostics.append(
                    self._error(
                        "checksums.sha256",
                        f"Checksum mismatch for {safe_path}",
                        "请重新导出角色包，或确认分发文件未被篡改。",
                        code="character_package.checksums.mismatch",
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
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

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
            "author_url",
            "license",
            "license_url",
            "license_detail",
            "description",
            "source",
            "attribution",
            "external_links",
            "repository",
            "signature",
            "checksums",
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
    def _trust_summary(manifest: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(manifest, dict):
            return {
                "author_declared": False,
                "source_declared": False,
                "license_declared": False,
                "signature_declared": False,
                "checksums_declared": False,
                "external_link_count": 0,
            }
        external_links = manifest.get("external_links")
        return {
            "author_declared": bool(manifest.get("author")),
            "source_declared": bool(manifest.get("source")),
            "license_declared": bool(manifest.get("license")),
            "signature_declared": isinstance(manifest.get("signature"), dict),
            "checksums_declared": isinstance(manifest.get("checksums"), dict),
            "external_link_count": len(external_links) if isinstance(external_links, list) else 0,
        }

    @staticmethod
    def _security_summary(
        manifest: dict[str, Any], diagnostics: list[ConfigDiagnostic]
    ) -> dict[str, Any]:
        codes = {item.code for item in diagnostics}
        return {
            "https_external_links_only": "character_package.external_link.scheme" not in codes,
            "checksums_valid": not any(code.startswith("character_package.checksums.") for code in codes),
            "has_undeclared_files": "character_package.security.undeclared_file" in codes,
            "signature_verification": "format_only",
            "declared_asset_count": len(manifest.get("assets", []) or [])
            if isinstance(manifest, dict) and isinstance(manifest.get("assets", []), list)
            else 0,
        }

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
