"""WebSocket round-trip through the public nginx endpoint (stdlib only).

Usage: python ws_check.py <base_url> <access_token> <project_id>
Connects to <base>/api/v1/ws, authenticates, subscribes, and prints "WS_OK"
once the 'subscribed' acknowledgement arrives.
"""

import base64
import json
import os
import socket
import struct
import sys
from urllib.parse import urlsplit


def frame(text: str) -> bytes:
    payload = text.encode()
    mask = os.urandom(4)
    header = bytearray([0x81])
    n = len(payload)
    if n < 126:
        header.append(0x80 | n)
    elif n < 65536:
        header += bytes([0x80 | 126]) + struct.pack(">H", n)
    else:
        header += bytes([0x80 | 127]) + struct.pack(">Q", n)
    return bytes(header) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))


def read_frame(sock) -> str:
    def recv(n):
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("closed")
            buf += chunk
        return buf

    b1, b2 = recv(2)
    n = b2 & 0x7F
    if n == 126:
        n = struct.unpack(">H", recv(2))[0]
    elif n == 127:
        n = struct.unpack(">Q", recv(8))[0]
    data = recv(n)
    if b1 & 0x0F == 0x8:
        raise ConnectionError(f"server closed: {data[:2].hex()}")
    return data.decode()


def main() -> None:
    base, token, project = sys.argv[1], sys.argv[2], sys.argv[3]
    u = urlsplit(base)
    sock = socket.create_connection((u.hostname, u.port or 80), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall(
        (
            f"GET /api/v1/ws HTTP/1.1\r\nHost: {u.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nOrigin: {base}\r\n\r\n"
        ).encode()
    )
    resp = b""
    while b"\r\n\r\n" not in resp:
        resp += sock.recv(1024)
    status = resp.split(b"\r\n", 1)[0]
    if b"101" not in status:
        sys.exit(f"handshake failed: {status!r}")
    sock.sendall(frame(json.dumps({"type": "auth", "token": token})))
    sock.sendall(frame(json.dumps({"type": "subscribe", "project_id": project})))
    for _ in range(20):
        msg = json.loads(read_frame(sock))
        if msg.get("kind") == "subscribed":
            print("WS_OK")
            return
        if msg.get("kind") == "error":
            sys.exit(f"ws error: {msg}")
    sys.exit("no subscription ack")


if __name__ == "__main__":
    main()
