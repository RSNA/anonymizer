"""Wait until a spawned MCP HTTP process accepts TCP on host:port."""

from __future__ import annotations

import socket
import subprocess
import time


def wait_for_mcp_tcp(
    host: str,
    port: int,
    proc: subprocess.Popen,
    *,
    timeout_s: float = 180.0,
    poll_s: float = 0.5,
) -> None:
    """
    Block until ``host:port`` accepts a TCP connection, or fail.

    Cold starts import TotalSegmentator → nnUNet → sklearn and often exceed a
    few seconds; callers must not race the client against a fixed sleep.

    Args:
        host: Bind host passed to ``--mcp HOST:PORT``.
        port: Bind port.
        proc: Server process; if it exits early, raise with exit code.
        timeout_s: Max wait before raising TimeoutError.
        poll_s: Delay between connection attempts.

    Raises:
        RuntimeError: Server process exited before the port opened.
        TimeoutError: Port still closed after ``timeout_s``.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"MCP server exited early (code={proc.returncode}) before "
                f"listening on {host}:{port}"
            )
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return
        except OSError:
            time.sleep(poll_s)
    raise TimeoutError(
        f"MCP server did not accept TCP on {host}:{port} within {timeout_s:.0f}s "
        "(cold import of TotalSegmentator/sklearn can take minutes; do not Ctrl-C)"
    )
