"""Thread-safe single-weights slot shared by XR classifier packages (leaf; no harmonize deps)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ModelSlot(Generic[T]):
    """Cache one loaded model keyed by its weight path."""

    def __init__(self, *, label: str) -> None:
        self._label = label
        self._lock = threading.Lock()
        self._model: T | None = None
        self._path: Path | None = None

    def get(self, path: Path, loader: Callable[[Path], T]) -> T:
        with self._lock:
            if self._model is not None and self._path == path:
                return self._model
            if not path.is_file():
                raise FileNotFoundError(f"{self._label} weights missing: {path}")
            logger.info("Loading %s weights from %s", self._label, path)
            self._model = loader(path)
            self._path = path
            return self._model

    def clear(self) -> None:
        """Drop in-memory weights (after remove/download)."""
        with self._lock:
            self._model = None
            self._path = None
