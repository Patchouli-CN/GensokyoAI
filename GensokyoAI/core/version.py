"""Package version helpers for Runtime metadata."""

from __future__ import annotations

import tomllib
from importlib import metadata
from pathlib import Path

PACKAGE_NAME = "GensokyoAI"
UNKNOWN_VERSION = "0+unknown"


def package_version(root_dir: Path | None = None) -> str:
    """Return the installed or source-tree package version.

    Prefer installed package metadata. When running directly from a source checkout,
    fall back to ``pyproject.toml`` under ``root_dir`` or the current working tree.
    """

    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return _package_version_from_pyproject(root_dir) or UNKNOWN_VERSION


def _package_version_from_pyproject(root_dir: Path | None = None) -> str | None:
    base = (root_dir or Path.cwd()).resolve()
    candidates = [base / "pyproject.toml"]
    module_root = Path(__file__).resolve().parents[2]
    if module_root != base:
        candidates.append(module_root / "pyproject.toml")

    for path in candidates:
        if not path.exists():
            continue
        try:
            with open(path, "rb") as file:
                data = tomllib.load(file)
        except Exception:
            continue
        version = data.get("project", {}).get("version")
        if isinstance(version, str) and version:
            return version
    return None
