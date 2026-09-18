# siril-mcp bridge — run inside Siril via:
#   pyscript -async /path/to/siril-mcp/bridge/bridge.py
#
# Requires: #version >= 1.3.0 (adjust if needed)
#version = 1.3.0

"""Long-lived MCP bridge process hosted by Siril's Python runtime."""

from __future__ import annotations

import json
import os
import socket
import struct
import tempfile
import threading
import time
import traceback
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from sirilpy import SirilInterface

PROTOCOL_VERSION = 1
HEADER = struct.Struct("!I")

SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "siril-mcp"
SOCKET_PATH = Path(os.environ.get("SIRIL_MCP_SOCKET", str(SUPPORT_DIR / "bridge.sock")))
STATUS_PATH = SUPPORT_DIR / "bridge.status.json"
PREVIEW_DIR = SUPPORT_DIR / "previews"
DEFAULT_MAX_EDGE = 1024


def log(msg: str) -> None:
    print(f"[siril-mcp] {msg}", flush=True)


def encode_message(obj: Dict[str, Any]) -> bytes:
    payload = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return HEADER.pack(len(payload)) + payload


def recv_exact(conn: socket.socket, n: int) -> bytes:
    chunks: List[bytes] = []
    remaining = n
    while remaining > 0:
        chunk = conn.recv(remaining)
        if not chunk:
            raise ConnectionError("client disconnected")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def recv_message(conn: socket.socket) -> Dict[str, Any]:
    header = recv_exact(conn, HEADER.size)
    (length,) = HEADER.unpack(header)
    if length > 64 * 1024 * 1024:
        raise ValueError(f"message too large: {length}")
    payload = recv_exact(conn, length)
    return json.loads(payload.decode("utf-8"))


def send_message(conn: socket.socket, obj: Dict[str, Any]) -> None:
    conn.sendall(encode_message(obj))


def write_status(extra: Optional[Dict[str, Any]] = None) -> None:
    SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "pid": os.getpid(),
        "socket": str(SOCKET_PATH),
        "protocol_version": PROTOCOL_VERSION,
        "updated_at": time.time(),
    }
    if extra:
        data.update(extra)
    STATUS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def downscale_uint8(arr: np.ndarray, max_edge: int) -> np.ndarray:
    if max_edge <= 0:
        return arr
    h, w = arr.shape[:2]
    longest = max(h, w)
    if longest <= max_edge:
        return arr
    scale = max_edge / float(longest)
    nh = max(1, int(round(h * scale)))
    nw = max(1, int(round(w * scale)))
    ys = (np.linspace(0, h - 1, nh)).astype(np.int32)
    xs = (np.linspace(0, w - 1, nw)).astype(np.int32)
    if arr.ndim == 2:
        return arr[ys][:, xs]
    return arr[ys][:, xs, :]


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack("!I", len(data)) + tag + data + struct.pack("!I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def write_png(path: Path, arr: np.ndarray) -> None:
    """Write an 8-bit grayscale or RGB numpy array as PNG (stdlib only)."""
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    if arr.ndim == 2:
        height, width = arr.shape
        color_type = 0  # greyscale
        raw = arr
    elif arr.ndim == 3 and arr.shape[2] in (1, 3):
        height, width, channels = arr.shape
        if channels == 1:
            color_type = 0
            raw = arr[:, :, 0]
        else:
            color_type = 2  # RGB
            raw = arr
    else:
        raise ValueError(f"unsupported array shape for PNG: {arr.shape}")

    rows = []
    if color_type == 0:
        for y in range(height):
            rows.append(b"\x00" + raw[y, :].tobytes())
    else:
        for y in range(height):
            rows.append(b"\x00" + raw[y, :, :].tobytes())
    compressed = zlib.compress(b"".join(rows), level=6)

    ihdr = struct.pack("!IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n"
    png += _png_chunk(b"IHDR", ihdr)
    png += _png_chunk(b"IDAT", compressed)
    png += _png_chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def _keywords_summary(siril: SirilInterface) -> Optional[Dict[str, Any]]:
    try:
        kw = siril.get_image_keywords()
    except Exception:
        return None
    if kw is None:
        return None
    interesting = [
        "object",
        "instrume",
        "telescop",
        "filter",
        "exposure",
        "date_obs",
        "key_gain",
        "key_offset",
        "binning_x",
        "binning_y",
        "focal_length",
        "pixel_size_x",
        "pixel_size_y",
        "stackcnt",
        "livetime",
        "bayer_pattern",
        "image_type",
        "ra",
        "dec",
        "pltsolvd",
    ]
    out: Dict[str, Any] = {}
    for name in interesting:
        if not hasattr(kw, name):
            continue
        val = getattr(kw, name)
        if val is None or val == "":
            continue
        if isinstance(val, (int, float)) and val == 0:
            continue
        if hasattr(val, "isoformat"):
            out[name] = val.isoformat()
        elif isinstance(val, bytes):
            out[name] = val.decode("utf-8", errors="replace")
        else:
            out[name] = val
    return out or None


def _stats_to_dict(stats) -> Dict[str, Any]:
    return {
        "total": stats.total,
        "ngoodpix": stats.ngoodpix,
        "mean": stats.mean,
        "median": stats.median,
        "sigma": stats.sigma,
        "mad": stats.mad,
        "min": stats.min,
        "max": stats.max,
    }


class Bridge:
    def __init__(self, siril: SirilInterface):
        self.siril = siril
        self._lock = threading.Lock()

    def handle(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            handler = getattr(self, f"do_{method}", None)
            if handler is None:
                raise ValueError(f"unknown method: {method}")
            return handler(params)

    def do_ping(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "ok": True,
            "protocol_version": PROTOCOL_VERSION,
            "pid": os.getpid(),
            "socket": str(SOCKET_PATH),
        }

    def do_get_state(self, params: Dict[str, Any]) -> Dict[str, Any]:
        image_loaded = bool(self.siril.is_image_loaded())
        seq_loaded = bool(self.siril.is_sequence_loaded())
        state: Dict[str, Any] = {
            "image_loaded": image_loaded,
            "sequence_loaded": seq_loaded,
            "working_directory": None,
            "filename": None,
            "shape": None,
            "selection": None,
            "keywords": None,
        }
        try:
            state["working_directory"] = self.siril.get_siril_wd()
        except Exception as e:
            state["working_directory_error"] = str(e)
        if image_loaded:
            try:
                state["filename"] = self.siril.get_image_filename()
            except Exception as e:
                state["filename_error"] = str(e)
            try:
                shape = self.siril.get_image_shape()
                if shape:
                    channels, height, width = shape
                    state["shape"] = {
                        "channels": channels,
                        "height": height,
                        "width": width,
                    }
            except Exception as e:
                state["shape_error"] = str(e)
            try:
                sel = self.siril.get_siril_selection()
                if sel:
                    x, y, w, h = sel
                    state["selection"] = {"x": x, "y": y, "w": w, "h": h}
            except Exception as e:
                state["selection_error"] = str(e)
            state["keywords"] = _keywords_summary(self.siril)
        return state

    def do_run_command(self, params: Dict[str, Any]) -> Dict[str, Any]:
        command = params.get("command")
        if not command or not isinstance(command, str):
            raise ValueError("command is required")
        args = params.get("args") or []
        if not isinstance(args, list):
            raise ValueError("args must be a list of strings")
        str_args = [str(a) for a in args]
        self.siril.cmd(command, *str_args)
        return {"command": command, "args": str_args, "status": "ok"}

    def do_run_script(self, params: Dict[str, Any]) -> Dict[str, Any]:
        body = params.get("script_body")
        kind = params.get("kind", "ssf")
        if not isinstance(body, str) or not body.strip():
            raise ValueError("script_body is required")
        if kind not in ("ssf", "py"):
            raise ValueError('kind must be "ssf" or "py"')

        suffix = ".ssf" if kind == "ssf" else ".py"
        SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(prefix="siril-mcp-", suffix=suffix, dir=str(SUPPORT_DIR))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(body)
            if kind == "ssf":
                # Execute line-by-line as commands (skip comments / blanks)
                for line in body.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.lower().startswith("requires"):
                        continue
                    parts = line.split()
                    self.siril.cmd(*parts)
            else:
                # Nested pyscript — sync so we wait for completion
                self.siril.cmd("pyscript", path)
            return {"kind": kind, "path": path, "status": "ok"}
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def do_get_preview(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.siril.is_image_loaded():
            raise RuntimeError("no image is loaded in Siril")

        max_edge = int(params.get("max_edge") or DEFAULT_MAX_EDGE)
        linked = bool(params.get("linked", True))
        save_debug = bool(params.get("save_debug_copy", True))
        roi = params.get("roi")
        shape = None
        if roi is not None:
            if not (isinstance(roi, list) and len(roi) == 4):
                raise ValueError("roi must be [x, y, w, h]")
            shape = [int(v) for v in roi]

        arr = self.siril.get_image_pixeldata(shape=shape, preview=True, linked=linked)
        if arr is None:
            raise RuntimeError("get_image_pixeldata returned None")

        # sirilpy may return (C,H,W) or (H,W)/(H,W,C) — normalize to HWC or HW
        if arr.ndim == 3 and arr.shape[0] in (1, 3) and arr.shape[0] < arr.shape[1] and arr.shape[0] < arr.shape[2]:
            # likely CHW
            arr = np.transpose(arr, (1, 2, 0))
            if arr.shape[2] == 1:
                arr = arr[:, :, 0]

        arr = downscale_uint8(arr, max_edge)
        PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        out_path = PREVIEW_DIR / f"preview-{int(time.time() * 1000)}.png"
        write_png(out_path, arr)

        h, w = arr.shape[:2]
        channels = 1 if arr.ndim == 2 else arr.shape[2]
        result = {
            "path": str(out_path),
            "width": int(w),
            "height": int(h),
            "channels": int(channels),
            "max_edge": max_edge,
            "roi": shape,
        }
        if not save_debug:
            # Still return path; MCP server reads it. Cleanup left to OS / later sweeps.
            pass
        return result

    def do_set_selection(self, params: Dict[str, Any]) -> Dict[str, Any]:
        for key in ("x", "y", "w", "h"):
            if key not in params:
                raise ValueError(f"missing {key}")
        x, y, w, h = (int(params["x"]), int(params["y"]), int(params["w"]), int(params["h"]))
        self.siril.set_siril_selection(x=x, y=y, w=w, h=h)
        return {"selection": {"x": x, "y": y, "w": w, "h": h}, "status": "ok"}

    def do_get_stats(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.siril.is_image_loaded():
            raise RuntimeError("no image is loaded in Siril")
        shape = self.siril.get_image_shape()
        if not shape:
            raise RuntimeError("could not read image shape")
        channels, height, width = shape
        channel_stats = []
        for ch in range(channels):
            st = self.siril.get_image_stats(ch)
            if st is None:
                channel_stats.append({"channel": ch, "stats": None})
            else:
                channel_stats.append({"channel": ch, "stats": _stats_to_dict(st)})
        return {
            "shape": {"channels": channels, "height": height, "width": width},
            "channels": channel_stats,
        }

    def do_undo(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self.siril.undo()
        return {"status": "ok"}


def handle_client(conn: socket.socket, bridge: Bridge) -> None:
    try:
        while True:
            try:
                request = recv_message(conn)
            except ConnectionError:
                break
            method = request.get("method")
            params = request.get("params") or {}
            try:
                if not isinstance(method, str):
                    raise ValueError("method must be a string")
                result = bridge.handle(method, params)
                send_message(conn, {"ok": True, "result": result})
            except Exception as e:
                send_message(
                    conn,
                    {
                        "ok": False,
                        "error": str(e),
                        "traceback": traceback.format_exc(),
                    },
                )
    finally:
        try:
            conn.close()
        except OSError:
            pass


def main() -> None:
    SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

    siril = SirilInterface()
    siril.connect()
    log("connected to Siril")

    if SOCKET_PATH.exists():
        try:
            SOCKET_PATH.unlink()
        except OSError:
            pass

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(str(SOCKET_PATH))
    server.listen(8)
    # Restrict socket permissions to the current user
    try:
        os.chmod(SOCKET_PATH, 0o600)
    except OSError:
        pass

    bridge = Bridge(siril)
    write_status({"status": "listening"})
    log(f"listening on {SOCKET_PATH}")

    try:
        while True:
            conn, _ = server.accept()
            thread = threading.Thread(target=handle_client, args=(conn, bridge), daemon=True)
            thread.start()
    except KeyboardInterrupt:
        log("shutting down")
    finally:
        try:
            server.close()
        except OSError:
            pass
        if SOCKET_PATH.exists():
            try:
                SOCKET_PATH.unlink()
            except OSError:
                pass
        write_status({"status": "stopped"})
        try:
            siril.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
