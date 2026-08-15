"""
Dual-stack entrypoint for the API service on Railway.

Railway private networking is IPv6 (services reach each other over
`<name>.railway.internal`), so the app must listen on `::` for the bot to call
it privately. But Railway's *public* edge reaches the container over IPv4, and a
plain `--host ::` socket is IPv6-only and refuses that — which shows up as a 502
on the public domain even though the app is up.

So we bind `::` with `IPV6_V6ONLY=0`: one socket that accepts BOTH IPv6 (private
networking) and IPv4-mapped (the public edge) connections, then hand it to
uvicorn.

Start command:  python -m api.run
"""

import os
import socket

import uvicorn


def _dual_stack_socket() -> socket.socket:
    """A `::`-bound listening socket that also accepts IPv4 (dual stack)."""
    port = int(os.environ.get("PORT", "8080"))
    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        # 0 => don't restrict to IPv6; accept IPv4-mapped connections too.
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    except (AttributeError, OSError):
        pass  # already dual-stack on this platform
    sock.bind(("::", port))
    sock.listen()
    return sock


def main() -> None:
    sock = _dual_stack_socket()
    server = uvicorn.Server(uvicorn.Config("api.main:app", log_level="info"))
    server.run(sockets=[sock])


if __name__ == "__main__":
    main()
