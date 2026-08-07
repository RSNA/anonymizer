"""Tests for AI model download progress tracking in utils.storage."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from anonymizer.utils.storage import (
    DownloadProgress,
    begin_model_download,
    end_model_download,
    get_model_download_progress,
    is_model_download_active,
    track_tqdm_model_download,
    update_model_download,
)


@pytest.fixture(autouse=True)
def _clear_progress() -> None:
    end_model_download("remove_pixel_phi")
    end_model_download("enable_harmonize")
    end_model_download("enable_face_blur")
    yield
    end_model_download("remove_pixel_phi")
    end_model_download("enable_harmonize")
    end_model_download("enable_face_blur")


def test_begin_update_end_lifecycle() -> None:
    begin_model_download("remove_pixel_phi", message="Starting OCR download")
    progress = get_model_download_progress("remove_pixel_phi")
    assert progress == DownloadProgress(message="Starting OCR download", fraction=None)
    assert is_model_download_active("remove_pixel_phi")

    update_model_download("remove_pixel_phi", message="Halfway", fraction=0.5)
    progress = get_model_download_progress("remove_pixel_phi")
    assert progress == DownloadProgress(message="Halfway", fraction=0.5)

    end_model_download("remove_pixel_phi")
    assert get_model_download_progress("remove_pixel_phi") is None
    assert not is_model_download_active("remove_pixel_phi")


def test_update_model_download_preserves_unset_fields() -> None:
    begin_model_download("enable_harmonize", message="Starting")
    update_model_download("enable_harmonize", fraction=0.25)
    progress = get_model_download_progress("enable_harmonize")
    assert progress == DownloadProgress(message="Starting", fraction=0.25)

    update_model_download("enable_harmonize", message="Extracting")
    progress = get_model_download_progress("enable_harmonize")
    assert progress == DownloadProgress(message="Extracting", fraction=0.25)


def test_track_tqdm_model_download_manage_lifecycle_false_preserves_tracker() -> None:
    fake_libs = MagicMock()

    class FakeTqdm:
        def __init__(self, *args, **kwargs):
            self.total = kwargs.get("total", 0)
            self.n = 0

        def update(self, n=1):
            self.n += n
            return True

        def close(self):
            return None

    fake_libs.tqdm = FakeTqdm
    begin_model_download("enable_harmonize", message="Outer download")

    with track_tqdm_model_download(
        "enable_harmonize",
        start_message="Task download",
        tqdm_module=fake_libs,
        manage_lifecycle=False,
    ):
        assert is_model_download_active("enable_harmonize")

    assert is_model_download_active("enable_harmonize")
    end_model_download("enable_harmonize")


def test_track_tqdm_model_download_reports_tqdm_and_prints() -> None:
    fake_libs = MagicMock()
    fake_tqdm_instances: list[MagicMock] = []
    progress_updates: list[tuple[str, float | None]] = []

    class FakeTqdm:
        def __init__(self, *args, **kwargs):
            self.total = kwargs.get("total", 0)
            self.n = 0
            fake_tqdm_instances.append(self)

        def update(self, n=1):
            self.n += n
            return True

        def close(self):
            return None

    fake_libs.tqdm = FakeTqdm

    with track_tqdm_model_download(
        "custom_model_key",
        start_message="Starting custom download",
        tqdm_module=fake_libs,
        on_progress=lambda message, fraction: progress_updates.append((message, fraction)),
    ):
        print("Download finished. Extracting...")
        bar = fake_libs.tqdm(total=1000, unit="B", unit_scale=True, desc="Downloading")
        bar.update(452)
        bar.update(548)

    assert get_model_download_progress("custom_model_key") is None
    assert progress_updates[0] == ("Starting custom download", None)
    assert progress_updates[1] == ("Download finished. Extracting...", None)
    assert any("Downloading:" in message and "/" in message for message, _ in progress_updates)
