"""ML execution environment: thread limits and sequential TotalSegmentator/nnUNet context."""

from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager, suppress
from typing import Iterator

logger = logging.getLogger(__name__)

# Serialize TotalSegmentator / nnUNet / XGBoost stages across the process.
# Concurrent entry (e.g. two Harmonize dialogs) previously caused hard crashes (SIGSEGV).
_ML_LOCK = threading.RLock()

# nnUNet reads these exact mixed-case names (see nnunetv2/utilities/default_n_proc_DA.py).
_NNUNET_N_PROC_DA = "nnUNet_n_proc_DA"
_NNUNET_DEF_N_PROC = "nnUNet_def_n_proc"

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
    logger.debug(
        "Threads [%s]: %d active — %s",
        stage,
        len(threads),
        ", ".join(t.name or repr(t.ident) for t in threads),
    )


@contextmanager
def sequential_ml_context(stage: str) -> Iterator[None]:
    """
    Force single-threaded native backends and exclusive ML entry for a stage.

    Prevents PyTorch/OpenMP/nnU-Net from spawning worker pools that compete for
    memory with TotalSegmentator and XGBoost inside the GUI process, and blocks
    concurrent Harmonize / Face Blur ML stages which are not process-safe together.
    """
    with _ML_LOCK:
        saved_env = {key: os.environ.get(key) for key in _THREAD_ENV_VARS}
        saved_nnunet = {
            _NNUNET_N_PROC_DA: os.environ.get(_NNUNET_N_PROC_DA),
            _NNUNET_DEF_N_PROC: os.environ.get(_NNUNET_DEF_N_PROC),
        }

        configure_macos_subprocess_env()
        for key in _THREAD_ENV_VARS:
            os.environ[key] = "1"
        os.environ[_NNUNET_N_PROC_DA] = "0"
        os.environ[_NNUNET_DEF_N_PROC] = "1"

        prior_intra = prior_inter = None
        try:
            import torch

            prior_intra = torch.get_num_threads()
            prior_inter = torch.get_num_interop_threads()
            torch.set_num_threads(1)
            with suppress(RuntimeError):
                torch.set_num_interop_threads(1)
        except ImportError:
            torch = None

        logger.debug("Sequential ML context start: %s", stage)
        log_active_threads(stage)

        ts_libs = None
        original_tqdm = None
        with suppress(ImportError):
            import totalsegmentator.libs as ts_libs
            from tqdm import tqdm as orig_tqdm

            class _NoMonitorTqdm(orig_tqdm):
                monitor_interval = 0

            original_tqdm = ts_libs.tqdm
            ts_libs.tqdm = _NoMonitorTqdm

        try:
            yield
        finally:
            if ts_libs is not None and original_tqdm is not None:
                ts_libs.tqdm = original_tqdm
            if torch is not None and prior_intra is not None:
                torch.set_num_threads(prior_intra)
                with suppress(RuntimeError):
                    if prior_inter is not None:
                        torch.set_num_interop_threads(prior_inter)

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

            logger.debug("Sequential ML context end: %s", stage)
