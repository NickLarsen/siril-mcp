"""Unit tests that do not require a live Siril session."""

from __future__ import annotations

import json
import socket
import threading
from pathlib import Path

import numpy as np

# Allow importing bridge helpers without sirilpy by loading PNG helpers via importlib
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from siril_mcp.protocol import BridgeClient, encode_message, recv_message, send_message


def _load_bridge_module():
    path = ROOT / "bridge" / "bridge.py"
    spec = importlib.util.spec_from_file_location("siril_mcp_bridge", path)
    # Stub sirilpy before exec
    import types

    fake = types.ModuleType("sirilpy")

    class SirilInterface:  # noqa: D401
        pass

    fake.SirilInterface = SirilInterface
    sys.modules["sirilpy"] = fake
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_png_roundtrip(tmp_path):
    bridge = _load_bridge_module()
    arr = np.zeros((32, 48, 3), dtype=np.uint8)
    arr[:, :, 0] = 255
    out = tmp_path / "t.png"
    bridge.write_png(out, arr)
    assert out.is_file()
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_downscale():
    bridge = _load_bridge_module()
    arr = np.zeros((2000, 1000), dtype=np.uint8)
    small = bridge.downscale_uint8(arr, 512)
    assert max(small.shape) <= 512


def test_protocol_echo(tmp_path):
    # macOS AF_UNIX paths are short; avoid long pytest temp prefixes
    import uuid

    sock_path = Path(f"/tmp/siril-mcp-test-{uuid.uuid4().hex}.sock")
    if sock_path.exists():
        sock_path.unlink()

    def server():
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            srv.bind(str(sock_path))
            srv.listen(1)
            conn, _ = srv.accept()
            req = recv_message(conn)
            send_message(conn, {"ok": True, "result": {"echo": req}})
            conn.close()
        finally:
            srv.close()
            if sock_path.exists():
                sock_path.unlink()

    t = threading.Thread(target=server)
    t.start()
    import time

    for _ in range(50):
        if sock_path.exists():
            break
        time.sleep(0.01)
    client = BridgeClient(str(sock_path), timeout=5)
    try:
        result = client.call("ping", {"x": 1})
        assert result["echo"]["method"] == "ping"
    finally:
        client.close()
        t.join(timeout=2)


def test_catalog_loads():
    catalog = json.loads((ROOT / "catalog" / "commands.json").read_text())
    assert catalog["count"] > 100
    assert any(c["name"] == "autostretch" for c in catalog["commands"])
