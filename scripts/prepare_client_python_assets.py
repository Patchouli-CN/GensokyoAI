#!/usr/bin/env python3
"""Prepare Python runtime source assets for the HakureiTerminal Flutter client.

This script copies the current Python engine source into
``hakureiterminal/assets/python``. It does not bundle a CPython runtime. Release
packaging must add a platform specific runtime under the final application
directory and point Dart bridge to that runtime.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = ROOT / "hakureiterminal" / "assets" / "python"
COPY_ITEMS = [
    "GensokyoAI",
    "characters",
    "config",
    "bridge_main.py",
    "pyproject.toml",
    "requirements.txt",
]
IGNORE_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
}


def ignore_patterns(directory: str, names: list[str]) -> set[str]:
    ignored = {name for name in names if name in IGNORE_NAMES}
    ignored.update(name for name in names if name.endswith((".pyc", ".pyo")))
    return ignored


def copy_item(source: Path, target: Path) -> None:
    if source.is_dir():
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target, ignore=ignore_patterns)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def prepare(target: Path, clean: bool = True) -> None:
    target = target.resolve()
    if clean and target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    for item in COPY_ITEMS:
        source = ROOT / item
        if not source.exists():
            raise FileNotFoundError(f"Required source asset does not exist: {source}")
        copy_item(source, target / item)

    readme = target / "README.txt"
    readme.write_text(
        "This directory contains HakureiTerminal Python bridge source assets.\n"
        "It intentionally does not contain a CPython runtime yet.\n"
        "Release builds must provide a bundled runtime and must not call system Python.\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare Flutter Python assets")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--no-clean", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    prepare(args.target, clean=not args.no_clean)
    print(f"Prepared Python assets at {args.target}")


if __name__ == "__main__":
    main()
