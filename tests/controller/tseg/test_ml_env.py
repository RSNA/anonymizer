"""Tests for sequential ML context exclusivity."""

from __future__ import annotations

import threading
import time

from anonymizer.controller.ai.tseg.ml_env import sequential_ml_context


def test_sequential_ml_context_serializes_concurrent_entry() -> None:
    active = 0
    max_active = 0
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def _worker() -> None:
        nonlocal active, max_active
        barrier.wait(timeout=2.0)
        with sequential_ml_context("test_stage"):
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with lock:
                active -= 1

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5.0)
        assert not thread.is_alive()

    assert max_active == 1
