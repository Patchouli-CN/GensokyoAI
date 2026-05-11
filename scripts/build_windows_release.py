#!/usr/bin/env python3
"""Build HakureiTerminal Windows release with bundled Python assets/runtime."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from prepare_client_python_assets import prepare as prepare_python_assets
from prepare_windows_runtime import DEFAULT_ARCH, DEFAULT_CACHE_DIR, DEFAULT_VERSION
from prepare_windows_runtime import prepare as prepare_windows_runtime

ROOT = Path(__file__).resolve().parents[1]
CLIENT_DIR = ROOT / "hakureiterminal"
CLIENT_PYTHON_ASSET_ROOT = CLIENT_DIR / "assets" / "python"
CLIENT_RUNTIME_DIR = CLIENT_PYTHON_ASSET_ROOT / "runtime"
RELEASE_DIR = CLIENT_DIR / "build" / "windows" / "x64" / "runner" / "Release"
RELEASE_PYTHON_ROOT = RELEASE_DIR / "python"


def run(command: list[str], cwd: Path | None = None) -> None:
    executable = command[0]
    resolved = shutil.which(executable)
    if resolved:
        command = [resolved, *command[1:]]
    print("Running:", " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)


def copy_python_bundle_to_release() -> None:
    if not CLIENT_PYTHON_ASSET_ROOT.exists():
        raise FileNotFoundError(f"Python assets do not exist: {CLIENT_PYTHON_ASSET_ROOT}")
    if RELEASE_PYTHON_ROOT.exists():
        shutil.rmtree(RELEASE_PYTHON_ROOT)
    shutil.copytree(CLIENT_PYTHON_ASSET_ROOT, RELEASE_PYTHON_ROOT)
    print(f"Copied Python bundle to {RELEASE_PYTHON_ROOT}")


def build_release(
    version: str,
    arch: str,
    cache_dir: Path,
    skip_runtime: bool,
    skip_flutter_build: bool,
    extra_requirements: list[str],
) -> None:
    preserved_runtime = ROOT / ".cache" / "python-runtime" / "preserved-runtime"
    if skip_runtime and CLIENT_RUNTIME_DIR.exists():
        if preserved_runtime.exists():
            shutil.rmtree(preserved_runtime)
        shutil.copytree(CLIENT_RUNTIME_DIR, preserved_runtime)

    prepare_python_assets(CLIENT_PYTHON_ASSET_ROOT, clean=True)

    if skip_runtime and preserved_runtime.exists():
        if CLIENT_RUNTIME_DIR.exists():
            shutil.rmtree(CLIENT_RUNTIME_DIR)
        shutil.copytree(preserved_runtime, CLIENT_RUNTIME_DIR)

    if not skip_runtime:
        prepare_windows_runtime(
            version=version,
            arch=arch,
            cache_dir=cache_dir.resolve(),
            target=CLIENT_RUNTIME_DIR.resolve(),
            requirements=(ROOT / "requirements.txt").resolve(),
            extra_requirements=extra_requirements,
            clean=True,
            skip_pip_install=False,
        )

    if not skip_flutter_build:
        run(["flutter", "build", "windows", "--release"], cwd=CLIENT_DIR)

    copy_python_bundle_to_release()
    print(f"Windows release is ready at {RELEASE_DIR}")
    print(f"Bundled Python executable: {RELEASE_PYTHON_ROOT / 'runtime' / 'python.exe'}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Windows release with bundled CPython")
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--arch", default=DEFAULT_ARCH, choices=["amd64", "win32", "arm64"])
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--skip-runtime", action="store_true")
    parser.add_argument("--skip-flutter-build", action="store_true")
    parser.add_argument(
        "--extra-requirement",
        action="append",
        default=[],
        help="Additional requirement to install into the embedded runtime. May be repeated.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_release(
        version=args.version,
        arch=args.arch,
        cache_dir=args.cache_dir,
        skip_runtime=args.skip_runtime,
        skip_flutter_build=args.skip_flutter_build,
        extra_requirements=args.extra_requirement,
    )


if __name__ == "__main__":
    main()
