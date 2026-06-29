"""Single-threaded ML runtime helpers for harmonize / tseg pipeline stages."""

from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger(__name__)

_THREAD_ENV_VARS = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "LOKY_MAX_CPU_COUNT",
)

# macOS: inherited MallocStackLogging makes forked/spawned worker processes spam stderr.
_MALLOC_ENV_VARS = (
    "MallocStackLogging",
    "MallocStackLoggingNoCompact",
    "MallocScribble",
    "MallocGuardEdges",
)


def configure_macos_subprocess_env() -> None:
    """Clear malloc debug env vars before TotalSegmentator spawns worker processes."""
    for key in _MALLOC_ENV_VARS:
        os.environ.pop(key, None)


def log_active_threads(stage: str) -> None:
    threads = threading.enumerate()
    logger.info(
        "Threads [%s]: %d active — %s",
        stage,
        len(threads),
        ", ".join(t.name or repr(t.ident) for t in threads),
    )


@contextmanager
def sequential_ml_context(stage: str) -> Iterator[None]:
    """
    Force single-threaded native backends during a harmonize ML stage.

    Prevents PyTorch/OpenMP/nnU-Net from spawning worker pools that compete for
    memory with TotalSegmentator and XGBoost inside the GUI process.
    """
    saved_env = {key: os.environ.get(key) for key in _THREAD_ENV_VARS}
    saved_nnunet = {
        "nnUNet_n_proc_DA": os.environ.get("nnUNet_n_proc_DA"),
        "nnUNet_def_n_proc": os.environ.get("nnUNet_def_n_proc"),
    }

    configure_macos_subprocess_env()
    for key in _THREAD_ENV_VARS:
        os.environ[key] = "1"
    os.environ["nnUNet_n_proc_DA"] = "0"
    os.environ["nnUNet_def_n_proc"] = "1"

    prior_intra = prior_inter = None
    try:
        import torch

        prior_intra = torch.get_num_threads()
        prior_inter = torch.get_num_interop_threads()
        torch.set_num_threads(1)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass
    except ImportError:
        torch = None

    logger.info("Sequential ML context start: %s", stage)
    log_active_threads(stage)

    try:
        yield
    finally:
        if torch is not None and prior_intra is not None:
            torch.set_num_threads(prior_intra)
            try:
                if prior_inter is not None:
                    torch.set_num_interop_threads(prior_inter)
            except RuntimeError:
                pass

        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for key, value in saved_nnunet.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

        logger.info("Sequential ML context end: %s", stage)
