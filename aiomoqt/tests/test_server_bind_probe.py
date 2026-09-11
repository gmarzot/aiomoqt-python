"""A server whose UDP port is taken must fail at serve() rather than log
"Listening" with no socket (the transport thread swallows EADDRINUSE)."""
import socket

import pytest

from aiomoqt.server import _check_udp_port_free


def test_busy_port_raises_and_free_port_passes():
    holder = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    holder.bind(("127.0.0.1", 0))
    port = holder.getsockname()[1]
    try:
        with pytest.raises(OSError, match=f"UDP port {port} unavailable"):
            _check_udp_port_free("127.0.0.1", port)
    finally:
        holder.close()
    _check_udp_port_free("0.0.0.0", port)   # released: no raise


def test_port_zero_is_never_probed():
    _check_udp_port_free("127.0.0.1", 0)
