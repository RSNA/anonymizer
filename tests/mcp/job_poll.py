"""Shared helper: drive an async MCP tool (pending + job_status) to completion."""

import time
from collections.abc import Callable
from typing import Any


def await_job(
    pending: dict[str, Any],
    job_status: Callable[..., dict[str, Any]],
    *,
    timeout_seconds: float = 300.0,
) -> dict[str, Any]:
    """
    Poll ``job_status`` for a ``pending`` tool result until it finishes.

    Args:
        pending: Tool result expected to carry status=pending and a job_id.
        job_status: ``job_status`` handler/client callable.
        timeout_seconds: Give up (AssertionError) after this long.

    Returns:
        The completed job's result payload with ``ok`` merged in, matching
        the shape synchronous tool results had before background jobs.
    """
    if pending.get("ok") is False:
        return pending
    assert pending.get("status") == "pending", pending
    job_id = pending["job_id"]
    deadline = time.monotonic() + timeout_seconds
    while True:
        status = job_status(job_id)
        if status.get("status") == "completed":
            return {"ok": status.get("ok", True), **(status.get("result") or {})}
        if status.get("status") == "failed":
            return {"ok": False, "error": status.get("error")}
        assert time.monotonic() < deadline, f"job {job_id} did not finish: {status}"
        time.sleep(0.05)
