"""Storage helpers exercised under tests/controller (utils/ is not in testpaths)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from anonymizer.utils.storage import (
    DownloadProgress,
    any_model_download_active,
    begin_model_download,
    count_quarantine_images,
    default_whitelist_path,
    end_model_download,
    get_model_download_progress,
    is_model_download_active,
    load_default_whitelist,
    load_project_whitelist,
    load_whitelist_from_txt,
    project_dir_from_series_path,
    project_whitelist_options_path,
    project_whitelist_path,
    save_project_whitelist,
    save_whitelist_to_txt,
    track_tqdm_model_download,
    update_model_download,
)


@pytest.fixture(autouse=True)
def _clear_progress() -> None:
    for key in ("remove_pixel_phi", "enable_harmonize", "enable_face_blur", "custom_model_key"):
        end_model_download(key)
    yield
    for key in ("remove_pixel_phi", "enable_harmonize", "enable_face_blur", "custom_model_key"):
        end_model_download(key)


def test_model_download_lifecycle_and_any_active() -> None:
    begin_model_download("remove_pixel_phi", message="Starting OCR download")
    assert get_model_download_progress("remove_pixel_phi") == DownloadProgress(
        message="Starting OCR download", fraction=None
    )
    assert is_model_download_active("remove_pixel_phi")
    assert any_model_download_active()

    update_model_download("remove_pixel_phi", message="Halfway", fraction=0.5)
    assert get_model_download_progress("remove_pixel_phi") == DownloadProgress(message="Halfway", fraction=0.5)

    end_model_download("remove_pixel_phi")
    assert get_model_download_progress("remove_pixel_phi") is None
    assert not is_model_download_active("remove_pixel_phi")
    assert not any_model_download_active()


def test_track_tqdm_model_download_reports_tqdm_and_prints() -> None:
    fake_libs = MagicMock()
    progress_updates: list[tuple[str, float | None]] = []

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
    assert any("Downloading:" in message and "/" in message for message, _ in progress_updates)


def test_track_tqdm_with_label_and_preserve_tracker() -> None:
    fake_libs = MagicMock()
    progress_updates: list[tuple[str, float | None]] = []

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
        label="total — CT anatomy 3 mm",
        tqdm_module=fake_libs,
        manage_lifecycle=False,
        on_progress=lambda message, fraction: progress_updates.append((message, fraction)),
    ):
        bar = fake_libs.tqdm(total=1000)
        bar.update(500)
        assert is_model_download_active("enable_harmonize")

    assert is_model_download_active("enable_harmonize")
    assert progress_updates[0][0].startswith("Downloading: total — CT anatomy 3 mm")
    end_model_download("enable_harmonize")


def test_whitelist_roundtrip_and_paths(tmp_path: Path) -> None:
    assert default_whitelist_path("CT").name == "ct.txt"
    assert project_whitelist_path(tmp_path, "MR").name == "mr.txt"
    assert project_whitelist_options_path(tmp_path, "US").name.endswith(".options.json")

    series = tmp_path / "public" / "pt" / "study" / "series"
    series.mkdir(parents=True)
    assert project_dir_from_series_path(series) == tmp_path
    shallow = tmp_path / "only"
    shallow.mkdir()
    # parents[3] may still resolve; just exercise the call
    _ = project_dir_from_series_path(shallow)

    wl_file = tmp_path / "wl.txt"
    save_whitelist_to_txt(wl_file, ["brain", "LIVER", "brain"])
    assert "BRAIN" in load_whitelist_from_txt(wl_file)
    assert "LIVER" in load_whitelist_from_txt(wl_file)

    saved = save_project_whitelist(tmp_path, "CT", ["Kidney", "Spleen"])
    assert saved.is_file()
    assert load_project_whitelist(tmp_path, "CT") == ["KIDNEY", "SPLEEN"]

    with pytest.raises(ValueError):
        save_project_whitelist(tmp_path, "CT", [])
    with pytest.raises(ValueError):
        load_whitelist_from_txt(tmp_path / "missing.txt")

    default_ct = load_default_whitelist("CT")
    assert isinstance(default_ct, list)
    assert isinstance(load_default_whitelist("CR"), list)


def test_count_quarantine_images(tmp_path: Path) -> None:
    assert count_quarantine_images(tmp_path / "missing") == 0
    q = tmp_path / "quarantine"
    (q / "a").mkdir(parents=True)
    (q / "a" / "bad.dcm").write_bytes(b"x")
    (q / "a" / "note.txt").write_text("n")
    assert count_quarantine_images(q) == 1
