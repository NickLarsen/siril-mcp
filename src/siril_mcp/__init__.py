"""Shared constants and paths for Siril MCP."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = PACKAGE_ROOT / "catalog" / "commands.json"

SUPPORT_DIR = Path(
    os.environ.get(
        "SIRIL_MCP_SUPPORT_DIR",
        Path.home() / "Library" / "Application Support" / "siril-mcp",
    )
)
SOCKET_PATH = Path(
    os.environ.get("SIRIL_MCP_SOCKET", str(SUPPORT_DIR / "bridge.sock"))
)
STATUS_PATH = SUPPORT_DIR / "bridge.status.json"
PREVIEW_DIR = SUPPORT_DIR / "previews"

DEFAULT_PREVIEW_MAX_EDGE = 1024
PROTOCOL_VERSION = 1
BRIDGE_DOWN_HINT = (
    "Siril MCP bridge is not running. In Siril, run: "
    "pyscript -async <path-to-siril-mcp>/bridge/bridge.py "
    "(or use Scripts → Start MCP Bridge after installing the helper)."
)
