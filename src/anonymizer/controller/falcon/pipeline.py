"""FALCON preprocessing pipeline (stub until Step 4)."""

from pathlib import Path


def preprocess_series_directory(series_directory: Path) -> tuple[object | None, str | None]:
    """Load and preprocess DICOM slices from a series directory.

    Returns:
        A ``(image, error)`` tuple. On success ``image`` is set and ``error`` is
        ``None``; on failure ``image`` is ``None`` and ``error`` describes why.
    """
    raise NotImplementedError("preprocess_series_directory is not yet implemented")
