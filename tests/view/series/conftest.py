"""Shared Tk/CustomTkinter scaffolding for Series View tests."""

from __future__ import annotations

import contextlib
import tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_THEME_PATH = Path(__file__).resolve().parents[3] / "src" / "anonymizer" / "assets" / "themes" / "rsna_theme.json"


@pytest.fixture(scope="session", autouse=True)
def _init_customtkinter_theme() -> None:
    import customtkinter as ctk

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme(str(_THEME_PATH))


@pytest.fixture
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    with contextlib.suppress(tk.TclError):
        root.destroy()


@pytest.fixture(autouse=True)
def _stub_viewer_icon_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid decoding on-disk play/pause icons (cwd-dependent) in every viewer test."""
    from PIL import Image

    from anonymizer.view.series import image as image_mod

    icon = Image.new("RGB", (28, 28), color=(0, 0, 0))
    monkeypatch.setattr(image_mod.Image, "open", lambda _path: icon)


@pytest.fixture
def mock_controller() -> MagicMock:
    controller = MagicMock()
    controller.get_phi_by_anon_patient_id.return_value = None
    controller.get_series_processing_status.return_value = None
    controller.series_has_face_blur.return_value = False
    controller.series_is_harmonized.return_value = True
    controller.format_series_processing_status.return_value = ""
    return controller
