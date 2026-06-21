#!/usr/bin/env python3
"""Compatibility wrapper for the HTTP/WebSocket Runtime entry point.

The actual implementation now lives in ``GensokyoAI.backends.web_server``.
This file is kept so that existing commands like ``python runtime_http.py``
continue to work.
"""

from __future__ import annotations

from GensokyoAI.backends.web_server.main import main

if __name__ == "__main__":
    main()
