"""角色校验命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from GensokyoAI.core.character_validator import CharacterValidator
from GensokyoAI.core.config_validator import ConfigDiagnostic


def validate_character_path(path: Path) -> dict[str, Any]:
    """校验单个角色 YAML 文件。"""

    validator = CharacterValidator()
    diagnostics = validator.validate_character_file(path)
    preview = None
    try:
        with open(path, encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
        preview = validator.build_preview(data, fallback_id=path.stem)
    except Exception:
        preview = None
    return _payload(path, diagnostics, preview)


def validate_character_directory(path: Path) -> dict[str, Any]:
    """批量扫描目录下的角色 YAML 文件。"""

    files = sorted([*path.glob("*.yaml"), *path.glob("*.yml")])
    items = [validate_character_path(file_path) for file_path in files]
    error_count = sum(item["error_count"] for item in items)
    warning_count = sum(item["warning_count"] for item in items)
    return {
        "ok": error_count == 0,
        "source": "directory",
        "path": str(path),
        "count": len(items),
        "items": items,
        "error_count": error_count,
        "warning_count": warning_count,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验 GensokyoAI 角色 YAML 文件")
    parser.add_argument("path", help="角色 YAML 文件或角色目录")
    parser.add_argument("--json", action="store_true", help="输出 JSON diagnostics")
    parser.add_argument("--recursive", action="store_true", help="递归扫描目录")
    args = parser.parse_args(argv)

    path = Path(args.path)
    if path.is_dir():
        payload = _validate_directory(path, recursive=args.recursive)
    else:
        payload = validate_character_path(path)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_human(payload)
    return 0 if payload.get("ok") else 1


def _validate_directory(path: Path, *, recursive: bool) -> dict[str, Any]:
    if not recursive:
        return validate_character_directory(path)
    files = sorted([*path.rglob("*.yaml"), *path.rglob("*.yml")])
    items = [validate_character_path(file_path) for file_path in files]
    error_count = sum(item["error_count"] for item in items)
    warning_count = sum(item["warning_count"] for item in items)
    return {
        "ok": error_count == 0,
        "source": "directory",
        "path": str(path),
        "recursive": True,
        "count": len(items),
        "items": items,
        "error_count": error_count,
        "warning_count": warning_count,
    }


def _payload(
    path: Path,
    diagnostics: list[ConfigDiagnostic],
    preview: dict[str, Any] | None,
) -> dict[str, Any]:
    errors = [item for item in diagnostics if item.severity == "error"]
    warnings = [item for item in diagnostics if item.severity == "warning"]
    return {
        "ok": not errors,
        "source": "file",
        "path": str(path),
        "preview": preview,
        "diagnostics": [item.to_dict() for item in diagnostics],
        "error_count": len(errors),
        "warning_count": len(warnings),
    }


def _print_human(payload: dict[str, Any]) -> None:
    if payload.get("source") == "directory":
        status = "OK" if payload.get("ok") else "FAILED"
        print(
            f"[{status}] {payload.get('path')} - "
            f"{payload.get('count', 0)} files, "
            f"{payload.get('error_count', 0)} errors, "
            f"{payload.get('warning_count', 0)} warnings"
        )
        for item in payload.get("items", []):
            _print_file_human(item, indent="  ")
        return
    _print_file_human(payload)


def _print_file_human(payload: dict[str, Any], *, indent: str = "") -> None:
    status = "OK" if payload.get("ok") else "FAILED"
    preview = payload.get("preview") or {}
    name = preview.get("name") or Path(str(payload.get("path"))).stem
    print(
        f"{indent}[{status}] {payload.get('path')} ({name}) - "
        f"{payload.get('error_count', 0)} errors, {payload.get('warning_count', 0)} warnings"
    )
    for diagnostic in payload.get("diagnostics", []):
        print(
            f"{indent}  - {diagnostic.get('severity')}: "
            f"{diagnostic.get('path')} {diagnostic.get('code')} - {diagnostic.get('message')}"
        )
        if diagnostic.get("suggestion"):
            print(f"{indent}    suggestion: {diagnostic.get('suggestion')}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
