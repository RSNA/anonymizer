"""Tests for AI feature download progress tracking."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from anonymizer.controller.tseg.runtime_status import TsWeightKind
from anonymizer.utils.download_progress import (
    DownloadProgress,
    begin_download,
    end_download,
    get_download_progress,
    is_download_active,
    track_segmentation_download,
    update_download,
)


@pytest.fixture(autouse=True)
def _clear_progress() -> None:
    end_download("remove_pixel_phi")
    end_download("enable_harmonize")
    end_download("enable_face_blur")
    yield
    end_download("remove_pixel_phi")
    end_download("enable_harmonize")
    end_download("enable_face_blur")


def test_begin_update_end_lifecycle() -> None:
    begin_download("remove_pixel_phi", message="Starting OCR download")
    progress = get_download_progress("remove_pixel_phi")
    assert progress == DownloadProgress(message="Starting OCR download", fraction=None)
    assert is_download_active("remove_pixel_phi")

    update_download("remove_pixel_phi", message="Halfway", fraction=0.5)
    progress = get_download_progress("remove_pixel_phi")
    assert progress == DownloadProgress(message="Halfway", fraction=0.5)

    end_download("remove_pixel_phi")
    assert get_download_progress("remove_pixel_phi") is None
    assert not is_download_active("remove_pixel_phi")


def test_update_download_preserves_unset_fields() -> None:
    begin_download("enable_harmonize", message="Starting")
    update_download("enable_harmonize", fraction=0.25)
    progress = get_download_progress("enable_harmonize")
    assert progress == DownloadProgress(message="Starting", fraction=0.25)

    update_download("enable_harmonize", message="Extracting")
    progress = get_download_progress("enable_harmonize")
    assert progress == DownloadProgress(message="Extracting", fraction=0.25)


def test_track_segmentation_download_reports_tqdm_and_prints() -> None:
    fake_libs = MagicMock()
    fake_tqdm_instances: list[MagicMock] = []

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

    with patch.dict("sys.modules", {"totalsegmentator.libs": fake_libs}):
        with patch(
            "anonymizer.controller.tseg.runtime_status.update_weight_download_detail",
        ) as sync_detail:
            with track_segmentation_download(TsWeightKind.ANATOMY, task_id=298):
                import totalsegmentator.libs as ts_libs

                print("Download finished. Extracting...")
                bar = ts_libs.tqdm(total=1000, unit="B", unit_scale=True, desc="Downloading")
                bar.update(452)
                bar.update(548)

    assert get_download_progress("enable_harmonize") is None
    sync_detail.assert_any_call(TsWeightKind.ANATOMY, "Downloading model for Task 298 ...")
    sync_detail.assert_any_call(TsWeightKind.ANATOMY, "Download finished. Extracting...")
    detail_messages = [call.args[1] for call in sync_detail.call_args_list]
    assert any("Downloading:" in message and "/" in message for message in detail_messages)
