"""Shared Tk/CustomTkinter scaffolding for Series View tests."""

import contextlib
import tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_THEME_PATH = Path(__file__).resolve().parents[3] / "src" / "anonymizer" / "assets" / "themes" / "rsna_theme.json"


@pytest.fixture(scope="session", autouse=True)
def _init_customtkinter_theme() -> None:
    """Match product light chrome so Treeview + CTk resolve the same appearance pairs."""
    import customtkinter as ctk

    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme(str(_THEME_PATH))


@pytest.fixture
def tk_root():
    """CTk root (not bare ``tk.Tk``) so nested CTkFrames get consistent theme colors."""
    import customtkinter as ctk

    root = ctk.CTk()
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
def mock_controller(tmp_path: Path) -> MagicMock:
    """Controller stub with a real project storage dir (exclude/whitelist I/O)."""
    controller = MagicMock()
    controller.model.storage_dir = tmp_path
    controller.get_phi_by_anon_patient_id.return_value = None
    controller.get_series_processing_status.return_value = None
    controller.series_has_face_blur.return_value = False
    controller.series_is_harmonized.return_value = True
    controller.format_series_processing_status.return_value = ""
    return controller
