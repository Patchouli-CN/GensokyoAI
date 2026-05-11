#!/usr/bin/env python3
"""HTTP/WebSocket Runtime entry point for GensokyoAI."""

from __future__ import annotations

import argparse
from pathlib import Path

from aiohttp import web

from GensokyoAI.runtime.http_adapter import create_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GensokyoAI HTTP/WebSocket runtime")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Root directory containing GensokyoAI, characters and config.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    web.run_app(
        create_app(root_dir=args.root.resolve()),
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
