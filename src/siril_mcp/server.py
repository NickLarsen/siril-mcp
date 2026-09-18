"""MCP stdio server that talks to the in-Siril Python bridge."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP, Image

from . import (
    BRIDGE_DOWN_HINT,
    CATALOG_PATH,
    DEFAULT_PREVIEW_MAX_EDGE,
    SOCKET_PATH,
)
from .protocol import BridgeClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("siril-mcp")

mcp = FastMCP("siril-mcp")


def _client() -> BridgeClient:
    return BridgeClient(str(SOCKET_PATH))


def _call(method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    client = _client()
    try:
        return client.call(method, params)
    except ConnectionError as e:
        raise RuntimeError(f"{BRIDGE_DOWN_HINT} ({e})") from e
    except Exception as e:
        # Reconnect next time; surface message to the agent
        raise RuntimeError(str(e)) from e
    finally:
        client.close()


def _load_catalog() -> Dict[str, Any]:
    if not CATALOG_PATH.is_file():
        return {"commands": [], "count": 0, "source": None}
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


@mcp.tool()
def siril_ping() -> str:
    """Check that the Siril MCP bridge is running inside Siril."""
    result = _call("ping")
    return json.dumps(result, indent=2)


@mcp.tool()
def siril_get_state() -> str:
    """Get live Siril state: loaded image, size, filename, selection, working directory."""
    result = _call("get_state")
    return json.dumps(result, indent=2)


@mcp.tool()
def siril_list_commands(query: str = "", scriptable_only: bool = True) -> str:
    """
    List Siril commands available for scripting.

    Args:
        query: Optional substring filter on command name or usage.
        scriptable_only: If true, only return scriptable commands.
    """
    catalog = _load_catalog()
    commands = catalog.get("commands", [])
    q = (query or "").strip().lower()
    out = []
    for cmd in commands:
        if scriptable_only and not cmd.get("scriptable", True):
            continue
        hay = f"{cmd.get('name', '')} {cmd.get('usage', '')}".lower()
        if q and q not in hay:
            continue
        out.append(cmd)
    return json.dumps(
        {
            "count": len(out),
            "query": query,
            "scriptable_only": scriptable_only,
            "commands": out,
        },
        indent=2,
    )


@mcp.tool()
def siril_run_command(command: str, args: Optional[List[str]] = None) -> str:
    """
    Run a single Siril command in the live GUI session.

    Args:
        command: Command name (e.g. "autostretch", "load", "cd").
        args: Optional list of argument strings.
    """
    result = _call("run_command", {"command": command, "args": args or []})
    return json.dumps(result, indent=2)


@mcp.tool()
def siril_run_script(script_body: str, kind: str = "ssf") -> str:
    """
    Run a multi-line Siril script (.ssf command script or .py via pyscript).

    Args:
        script_body: Full script contents.
        kind: "ssf" for command scripts, "py" for Python (executed with pyscript).
    """
    if kind not in ("ssf", "py"):
        raise ValueError('kind must be "ssf" or "py"')
    result = _call("run_script", {"script_body": script_body, "kind": kind})
    return json.dumps(result, indent=2)


@mcp.tool()
def siril_get_preview(
    max_edge: int = DEFAULT_PREVIEW_MAX_EDGE,
    x: Optional[int] = None,
    y: Optional[int] = None,
    w: Optional[int] = None,
    h: Optional[int] = None,
    linked: bool = True,
    save_debug_copy: bool = True,
) -> Image:
    """
    Return an 8-bit autostretched preview of the current Siril image (or a ROI).

    Args:
        max_edge: Maximum width or height of the returned PNG.
        x, y, w, h: Optional ROI in image pixel coordinates (omit all for full image).
        linked: Use linked autostretch when True.
        save_debug_copy: Also write a PNG under Application Support for debugging.
    """
    params: Dict[str, Any] = {
        "max_edge": max_edge,
        "linked": linked,
        "save_debug_copy": save_debug_copy,
    }
    if None not in (x, y, w, h):
        params["roi"] = [int(x), int(y), int(w), int(h)]
    elif any(v is not None for v in (x, y, w, h)):
        raise ValueError("Provide all of x, y, w, h for a ROI, or none of them")

    result = _call("get_preview", params)
    png_path = result.get("path")
    if not png_path or not Path(png_path).is_file():
        raise RuntimeError("Bridge did not return a preview image path")
    # FastMCP Image accepts a path or bytes
    return Image(path=png_path)


@mcp.tool()
def siril_set_selection(x: int, y: int, w: int, h: int) -> str:
    """Set the Siril image selection rectangle (x, y, width, height)."""
    result = _call("set_selection", {"x": x, "y": y, "w": w, "h": h})
    return json.dumps(result, indent=2)


@mcp.tool()
def siril_get_stats() -> str:
    """Get per-channel statistics for the currently loaded image."""
    result = _call("get_stats")
    return json.dumps(result, indent=2)


@mcp.tool()
def siril_undo() -> str:
    """Undo the last Siril operation (if undo history is available)."""
    result = _call("undo")
    return json.dumps(result, indent=2)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
