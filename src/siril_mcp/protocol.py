"""Length-prefixed JSON protocol over a Unix domain socket."""

from __future__ import annotations

import json
import socket
import struct
from typing import Any, Dict, Optional

HEADER = struct.Struct("!I")  # uint32 big-endian payload length


def encode_message(obj: Dict[str, Any]) -> bytes:
    payload = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return HEADER.pack(len(payload)) + payload


def recv_exact(sock: socket.socket, n: int) -> bytes:
    chunks: list[bytes] = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("Connection closed while reading")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def recv_message(sock: socket.socket) -> Dict[str, Any]:
    header = recv_exact(sock, HEADER.size)
    (length,) = HEADER.unpack(header)
    if length > 64 * 1024 * 1024:
        raise ValueError(f"Message too large: {length} bytes")
    payload = recv_exact(sock, length)
    return json.loads(payload.decode("utf-8"))


def send_message(sock: socket.socket, obj: Dict[str, Any]) -> None:
    sock.sendall(encode_message(obj))


class BridgeClient:
    """Client for the in-Siril bridge socket."""

    def __init__(self, socket_path: str, timeout: float = 180.0):
        self.socket_path = socket_path
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None

    def connect(self) -> None:
        if self._sock is not None:
            return
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(self.socket_path)
        except OSError as e:
            sock.close()
            raise ConnectionError(str(e)) from e
        self._sock = sock

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self.connect()
        assert self._sock is not None
        request = {"method": method, "params": params or {}}
        try:
            send_message(self._sock, request)
            response = recv_message(self._sock)
        except Exception:
            self.close()
            raise
        if not response.get("ok", False):
            raise RuntimeError(response.get("error", "Unknown bridge error"))
        return response.get("result") or {}
