import contextlib
import copy
import difflib
import gc
import logging
import os
import queue
import threading
import tkinter as tk
from enum import StrEnum, auto
from pathlib import Path
from pprint import pformat
from tkinter import messagebox

import customtkinter as ctk
import numpy as np
import torch
from easyocr import Reader
from pydicom import Dataset, dcmread

from anonymizer.controller.blur_face import (
    FaceBlurMode,
    FaceBlurPreviewResult,
    SeriesVolumeContext,
    apply_face_blur_preview_to_series_frames,
    apply_series_face_blur_metadata,
    hu_stack_to_viewer_frames,
    mask_slice_segmentations,
    preview_face_blur,
)
from anonymizer.controller.blur_face_gate import (
    FaceBlurEligibility,
    FaceBlurGateDecision,
    evaluate_face_blur_eligibility,
    face_blur_gate_message,
)
from anonymizer.controller.create_projections import (
    apply_windowing,
    get_wl_ww,
    load_series_frames,
    save_series_frames,
)
from anonymizer.controller.harmonize import series_description_is_harmonized
from anonymizer.controller.remove_pixel_phi import (
    LayerType,
    OCRText,
    UserRectangle,
    apply_series_view_pixel_phi,
    blackout_rectangular_areas,
    collect_series_view_pixel_phi_texts,
    detect_text,
    remove_text,
)
from anonymizer.controller.tseg.cache import clear_tseg_series_cache, tseg_cache_summary
from anonymizer.controller.tseg.config import ENABLE_TSEG_FACE, TSEG_CACHE_DIRNAME
from anonymizer.controller.tseg.dicom_geometry import (
    SeriesGeometryResult,
    format_series_view_geometry_line,
    load_geometry_cache,
    resolve_series_geometry,
    stackable_dicom_paths,
)
from anonymizer.model.anonymizer import AnonymizerModel
from anonymizer.utils.memory import log_process_memory
from anonymizer.utils.storage import (
    get_dcm_files,
    load_default_whitelist,
    load_project_whitelist,
    save_project_whitelist,
)
from anonymizer.utils.translate import _
from anonymizer.view.blur_face_results import (
    FACE_MASK_OVERLAY_ALPHA,
    FACE_MASK_OVERLAY_COLOR,
    face_blur_mode_from_menu_label,
    face_blur_mode_menu_values,
    face_review_wl_ww,
    format_face_blur_progress_status,
    format_face_blur_qa_summary,
)
from anonymizer.view.harmonize_results import show_harmonize_results_view
from anonymizer.view.image import ImageViewer

logger = logging.getLogger(__name__)


class SeriesLoadError(Exception):
    """Raised when DICOM series pixels cannot be loaded for Series View."""


def show_series_view(
    parent: tk.Misc,
    *,
    anon_model: AnonymizerModel,
    series_path: Path,
) -> "SeriesView | None":
    """Open Series View with a loading shell while DICOM pixels are read in the background."""
    if not series_path.is_dir():
        messagebox.showerror(
            title=_("Series View"),
            message=_("Could not load this series.") + f"\n\n{series_path}",
            parent=parent,
        )
        return None
    log_process_memory("series_view_open", extra=str(series_path.name))
    return SeriesView(parent, anon_model=anon_model, series_path=series_path)


# Edit Contexts:
class EditContext(StrEnum):
    FRAME = auto()  # apply edits to current frame only
    SERIES = auto()  # apply edits to every frame in series
    # TODO: PROJECT = auto()  # apply edits to all series in project


class SeriesView(tk.Toplevel):
    BUTTON_WIDTH = 100
    PAD = 10
    BLUR_POLL_MS = 200
    LOAD_POLL_MS = 100
    PROGRESS_SLICE_THRESHOLD = 400
    DEFAULT_WIDTH = 960
    DEFAULT_HEIGHT = 640
    STATUS_WRAPLENGTH = 600
    LOADING_SHELL_WIDTH = 420
    LOADING_SHELL_HEIGHT = 72
    LOADING_SHELL_PAD = 12
    LOAD_PROGRESS_PULSE_MS = 180

    def __init__(self, parent, anon_model: AnonymizerModel, series_path: Path):
        super().__init__(master=parent)

        self._parent = parent
        self._anon_model = anon_model
        self._series_path = series_path
        self._ocr_reader = None  # only created if user clicks "Detect Text" button
        self.edit_context: EditContext = EditContext.FRAME
        self.detected_text: dict[int, list[OCRText]] = {}  # Store all detected text per frame
        self._whitelist_changed = False
        self._loading = True
        self._load_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._loading_shell: ctk.CTkFrame | None = None
        self._load_progress: ctk.CTkProgressBar | None = None
        self._load_progress_after_id: str | None = None
        self._load_progress_value = 0.0
        self._show_load_progress = self._series_needs_load_progress(series_path)

        self._ds: Dataset | None = None
        self._frames: np.ndarray | None = None
        self._slice_paths: tuple[Path, ...] = ()
        self.single_frame = False
        self._dicom_wl: float | None = None
        self._dicom_ww: float | None = None
        self._face_blur_preview_pending = False
        self._blur_preview = None
        self._blur_review_saved = None
        self._series_geometry: SeriesGeometryResult | None = None
        self._face_blur_eligibility_cache: FaceBlurEligibility | None = None
        self._face_blur_eligibility_geometry: SeriesGeometryResult | None = None
        self._blur_running = False
        self._blur_poll_after_id: str | None = None
        self._blur_review_after_id: str | None = None
        self._rebuild_after_id: str | None = None
        self._rebuild_pending = False
        self._ui_rebuilding = False

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Escape>", self._escape_keypress)
        self.bind("<Configure>", self._on_series_configure)

        if self._show_load_progress:
            self._show_loading_shell()
            self.update_idletasks()
            self.deiconify()
        else:
            self._prepare_hidden_load()
        self.lift()

        log_process_memory("series_view_init", extra=str(series_path.name))

        threading.Thread(
            target=self._load_worker,
            name="SeriesViewLoadWorker",
            daemon=True,
        ).start()
        self.after(self.LOAD_POLL_MS, self._poll_load_worker)

    def _show_loading_shell(self) -> None:
        self.withdraw()
        self.title(_("Series View"))
        width = self.LOADING_SHELL_WIDTH
        height = self.LOADING_SHELL_HEIGHT
        self.geometry(f"{width}x{height}")
        self.minsize(width, height)
        self.resizable(False, False)

        self._loading_shell = ctk.CTkFrame(self, fg_color="transparent")
        pad = self.LOADING_SHELL_PAD
        self._loading_shell.pack(fill="both", expand=True, padx=pad, pady=pad)

        ctk.CTkLabel(
            self._loading_shell,
            text=f"{_('Loading series')}…  {self._series_path.name}",
            anchor="w",
        ).pack(fill="x", pady=(0, 8))

        progress_width = width - (2 * pad)
        self._load_progress = ctk.CTkProgressBar(self._loading_shell, width=progress_width)
        self._load_progress.pack(fill="x")
        self._load_progress_value = 0.0
        self._load_progress.set(0.0)
        self._pulse_load_progress()

        self._position_near_parent(width=width, height=height)

    def _pulse_load_progress(self) -> None:
        if not self._loading or self._load_progress is None:
            return
        self._load_progress_value = min(0.92, self._load_progress_value + 0.035)
        self._load_progress.set(self._load_progress_value)
        self._load_progress_after_id = self.after(
            self.LOAD_PROGRESS_PULSE_MS,
            self._pulse_load_progress,
        )

    def _stop_load_progress_pulse(self) -> None:
        if self._load_progress_after_id is None:
            return
        with contextlib.suppress(tk.TclError):
            self.after_cancel(self._load_progress_after_id)
        self._load_progress_after_id = None

    def _prepare_hidden_load(self) -> None:
        """Keep the window hidden while short series load (no progress flicker)."""
        self.withdraw()
        self.title(_("Series View"))
        self.geometry(f"{self.DEFAULT_WIDTH}x{self.DEFAULT_HEIGHT}")
        self._position_near_parent(width=self.DEFAULT_WIDTH, height=self.DEFAULT_HEIGHT)

    @staticmethod
    def _count_series_slices(series_path: Path) -> int:
        try:
            return len(stackable_dicom_paths(series_path))
        except ValueError:
            return len(get_dcm_files(series_path))

    @classmethod
    def _series_needs_load_progress(cls, series_path: Path) -> bool:
        return cls._count_series_slices(series_path) > cls.PROGRESS_SLICE_THRESHOLD

    def _position_near_parent(self, *, width: int | None = None, height: int | None = None) -> None:
        """Place the window near the parent (Projection View), matching pre-loader behavior."""
        self.update_idletasks()
        width = width or self.winfo_width()
        height = height or self.winfo_height()
        try:
            self._parent.update_idletasks()
            pos_x = self._parent.winfo_rootx() + 30
            pos_y = self._parent.winfo_rooty() + 30
        except tk.TclError:
            pos_x = (self.winfo_screenwidth() - width) // 2
            pos_y = (self.winfo_screenheight() - height) // 2
        pos_x = max(0, min(pos_x, self.winfo_screenwidth() - width))
        pos_y = max(0, min(pos_y, self.winfo_screenheight() - height))
        self.geometry(f"{width}x{height}+{pos_x}+{pos_y}")

    def _slice_stack(self) -> np.ndarray:
        """Return the slice-only stack (no projections) from the viewer frame buffer."""
        if self._frames is None:
            raise SeriesLoadError("Series View has no loaded frames")
        return self._frames if self.single_frame else self._frames[3:]

    @staticmethod
    def _build_viewer_frames(series_frames: np.ndarray) -> np.ndarray:
        """Build projection + slice stack in one buffer (avoids an extra full-volume copy)."""
        slice_count = series_frames.shape[0]
        frames = np.empty((slice_count + 3,) + series_frames.shape[1:], dtype=series_frames.dtype)
        np.copyto(frames[3:], series_frames)
        del series_frames

        proj_min = np.copy(frames[3])
        proj_max = np.copy(frames[3])
        proj_sum = frames[3].astype(np.float32, copy=True)
        for slice_index in range(4, frames.shape[0]):
            slice_frame = frames[slice_index]
            np.minimum(proj_min, slice_frame, out=proj_min)
            np.maximum(proj_max, slice_frame, out=proj_max)
            proj_sum += slice_frame

        frames[0] = proj_min
        frames[2] = proj_max
        frames[1] = (proj_sum / slice_count).astype(frames.dtype, copy=False)
        return frames

    @staticmethod
    def _load_series_data(series_path: Path) -> tuple[Dataset, np.ndarray, tuple[Path, ...], SeriesGeometryResult | None]:
        log_process_memory("load_series_data_start", extra=str(series_path.name))
        ds, series_frames, slice_paths = load_series_frames(series_path)
        if ds is None or series_frames is None:
            raise SeriesLoadError(f"Error loading frames from {series_path}")

        log_process_memory(
            "after_load_series_frames",
            array=series_frames,
            extra=str(series_path.name),
        )

        if series_frames.shape[0] == 1:
            frames = series_frames
        else:
            frames = SeriesView._build_viewer_frames(series_frames)
            del series_frames
            gc.collect()
            log_process_memory(
                "after_build_viewer_frames",
                array=frames,
                extra=str(series_path.name),
            )

        series_geometry: SeriesGeometryResult | None = None
        if getattr(ds, "Modality", None) == "CT":
            series_geometry = load_geometry_cache(series_path)

        log_process_memory(
            "load_series_data_done",
            array=frames,
            extra=str(series_path.name),
        )
        return ds, frames, slice_paths, series_geometry

    def _ensure_series_geometry(self) -> SeriesGeometryResult | None:
        if self._series_geometry is not None:
            return self._series_geometry
        if getattr(self._ds, "Modality", None) != "CT":
            return None
        self._series_geometry = load_geometry_cache(self._series_path)
        if self._series_geometry is not None:
            return self._series_geometry
        try:
            self._log_series_memory("resolve_series_geometry_start")
            self._series_geometry = resolve_series_geometry(self._series_path)
            self._log_series_memory("resolve_series_geometry_done")
        except Exception as exc:
            logger.warning("Could not resolve series geometry for %s: %s", self._series_path, exc)
        return self._series_geometry

    def _load_worker(self) -> None:
        self._log_series_memory("load_worker_start")
        try:
            payload = self._load_series_data(self._series_path)
            _, frames, _, _ = payload
            self._log_series_memory("load_worker_done", array=frames)
            self._load_queue.put(("done", payload))
        except SeriesLoadError as exc:
            self._load_queue.put(("error", exc))
        except (ValueError, FileNotFoundError, PermissionError) as exc:
            self._load_queue.put(("error", SeriesLoadError(str(exc))))
        except Exception as exc:
            logger.exception("Series View load failed for %s", self._series_path)
            self._load_queue.put(("error", SeriesLoadError(str(exc))))

    def _poll_load_worker(self) -> None:
        if not self.winfo_exists() or not self._loading:
            return

        while True:
            try:
                kind, payload = self._load_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "done":
                ds, frames, slice_paths, series_geometry = payload
                self._finish_loading(
                    ds=ds,
                    frames=frames,
                    slice_paths=slice_paths,
                    series_geometry=series_geometry,
                )
                return
            if kind == "error":
                self._loading = False
                logger.error("Could not open series view for %s: %s", self._series_path, payload)
                messagebox.showerror(
                    title=_("Series View"),
                    message=_("Could not load this series.")
                    + f"\n\n{self._series_path}\n\n{payload}",
                    parent=self._parent,
                )
                self.destroy()
                return

        self.after(self.LOAD_POLL_MS, self._poll_load_worker)

    def _finish_loading(
        self,
        *,
        ds: Dataset,
        frames: np.ndarray,
        slice_paths: tuple[Path, ...],
        series_geometry: SeriesGeometryResult | None,
    ) -> None:
        self._log_series_memory("finish_loading_start", array=frames)
        self._loading = False
        self._ds = ds
        self._frames = frames
        self._slice_paths = slice_paths
        self._series_geometry = series_geometry
        self.single_frame = frames.shape[0] == 1
        self._remember_dicom_wl_ww(ds)

        self.withdraw()
        self._stop_load_progress_pulse()
        if self._loading_shell is not None:
            self._loading_shell.destroy()
            self._loading_shell = None
            self._load_progress = None
            self.update_idletasks()

        self.resizable(True, True)
        self._build_ui()
        self._log_series_memory("after_build_ui", array=self._frames)
        self._update_title()
        self.deiconify()
        self.lift()
        self.focus_force()
        self._apply_initial_viewer_display()
        self._log_series_memory("after_viewer_initial_display", array=self._frames)
        self.after_idle(self._refresh_analysis_cache_ui)

    def _remember_dicom_wl_ww(self, ds: Dataset | None = None) -> tuple[float, float]:
        """Read and cache WL/WW from DICOM headers (not viewer-adjusted values)."""
        source: Dataset | None = ds if ds is not None else self._ds
        if self._slice_paths:
            try:
                source = dcmread(str(self._slice_paths[0]), stop_before_pixels=True, force=True)
            except Exception as exc:
                logger.debug("Could not refresh WL/WW from %s: %s", self._slice_paths[0], exc)
        if source is None:
            self._dicom_wl, self._dicom_ww = 127.5, 255.0
            return self._dicom_wl, self._dicom_ww
        wl, ww = get_wl_ww(source)
        self._dicom_wl, self._dicom_ww = wl, ww
        return wl, ww

    def _dicom_wl_ww(self) -> tuple[float, float]:
        if self._dicom_wl is not None and self._dicom_ww is not None:
            return self._dicom_wl, self._dicom_ww
        return self._remember_dicom_wl_ww()

    def _viewer_wl_ww(self) -> tuple[float, float]:
        if self._blur_preview is not None and self._ds is not None:
            return face_review_wl_ww(self._ds)
        return self._dicom_wl_ww()

    def _sync_viewer_wl_ww(self) -> None:
        if not hasattr(self, "image_viewer"):
            return
        wl, ww = self._viewer_wl_ww()
        self.image_viewer.set_wlww_sync(wl, ww)

    def _fit_window_to_content(self) -> None:
        """Expand the window to fit the built UI (V18 auto-size after synchronous build)."""
        self.update_idletasks()
        req_w = max(self.winfo_reqwidth(), self.DEFAULT_WIDTH)
        req_h = max(self.winfo_reqheight(), self.DEFAULT_HEIGHT)
        max_w = int(self.winfo_screenwidth() * ImageViewer.MAX_SCREEN_PERCENTAGE)
        max_h = int(self.winfo_screenheight() * ImageViewer.MAX_SCREEN_PERCENTAGE)
        width = min(req_w, max_w)
        height = min(req_h, max_h)
        self.minsize(min(640, width), min(480, height))

        pos_x, pos_y = self.winfo_x(), self.winfo_y()
        if pos_x <= 0 and pos_y <= 0:
            self._position_near_parent(width=width, height=height)
        else:
            self.geometry(f"{width}x{height}+{max(0, pos_x)}+{max(0, pos_y)}")

    def _apply_initial_viewer_display(self) -> None:
        """Apply master-style viewer sizing once the Series View window is mapped."""
        if not hasattr(self, "image_viewer") or self.image_viewer is None:
            return
        viewer = self.image_viewer
        viewer.detach_companion_stack()
        self.update_idletasks()
        viewer._resize_to_viewport_enabled = True
        viewer._set_initial_size()
        self._fit_window_to_content()
        self.update_idletasks()
        viewer.on_resize()

    def _update_status_label_wraplength(self) -> None:
        if not hasattr(self, "_status_label"):
            return
        wrap = max(320, self.winfo_width() or self.STATUS_WRAPLENGTH) - (3 * self.PAD)
        with contextlib.suppress(tk.TclError):
            self._status_label.configure(wraplength=wrap)

    def _on_series_configure(self, event: tk.Event) -> None:
        if event.widget is not self or self._loading or self._ui_rebuilding:
            return
        self._update_status_label_wraplength()

    def _capture_whitelist_items(self) -> list[str]:
        if not hasattr(self, "whitelist"):
            return []
        return [str(item) for item in self.whitelist.get(0, tk.END)]

    def _restore_whitelist_items(self, items: list[str]) -> None:
        if not hasattr(self, "whitelist"):
            return
        self.whitelist.delete(0, tk.END)
        for item in items:
            self.whitelist.insert(tk.END, item)

    def _series_interaction_allowed(self) -> bool:
        return not self._blur_running and not self._ui_rebuilding and not self._loading

    def _set_series_interaction_enabled(self, enabled: bool) -> None:
        """Enable or disable Series View controls and the image viewer."""
        if not self.winfo_exists():
            return

        busy = not enabled
        widget_state = "disabled" if busy else "normal"
        listbox_state = tk.DISABLED if busy else tk.NORMAL

        for attr in (
            "detect_button",
            "remove_button",
            "blackout_button",
            "harmonize_button",
            "blur_face_button",
            "blur_face_mode_menu",
            "clear_ts_cache_button",
            "edit_context_combo_box",
            "whitelist_entry",
            "whitelist_defaults_button",
            "whitelist_clear_button",
        ):
            widget = getattr(self, attr, None)
            if widget is not None:
                with contextlib.suppress(tk.TclError):
                    widget.configure(state=widget_state)

        if hasattr(self, "whitelist"):
            with contextlib.suppress(tk.TclError):
                self.whitelist.configure(state=listbox_state)

        if hasattr(self, "save_button"):
            with contextlib.suppress(tk.TclError):
                if busy:
                    self.save_button.configure(state="disabled")
                elif self._face_blur_preview_pending or self._blur_preview is not None:
                    self.save_button.configure(state="normal")
                else:
                    self.save_button.configure(state="disabled")

        if hasattr(self, "image_viewer"):
            with contextlib.suppress(tk.TclError):
                self.image_viewer.set_interaction_enabled(enabled)

        with contextlib.suppress(tk.TclError):
            self.configure(cursor="watch" if busy else "")

        if enabled:
            self._refresh_blur_face_ui()

    def _stop_blur_worker_poll(self) -> None:
        if self._blur_poll_after_id is None:
            return
        with contextlib.suppress(tk.TclError):
            self.after_cancel(self._blur_poll_after_id)
        self._blur_poll_after_id = None

    def _stop_blur_review_deferred(self) -> None:
        if self._blur_review_after_id is None:
            return
        with contextlib.suppress(tk.TclError):
            self.after_cancel(self._blur_review_after_id)
        self._blur_review_after_id = None

    def _flush_pending_rebuild_ui(self) -> None:
        if not self._rebuild_pending or self._blur_running or self._blur_preview is not None:
            return
        self._rebuild_pending = False
        self._schedule_rebuild_ui()

    def _stop_rebuild_ui(self) -> None:
        if self._rebuild_after_id is None:
            return
        with contextlib.suppress(tk.TclError):
            self.after_cancel(self._rebuild_after_id)
        self._rebuild_after_id = None

    def _schedule_rebuild_ui(self) -> None:
        """Rebuild widgets on the Tk main thread after cache clear or similar."""
        if not self.winfo_exists():
            return
        if self._blur_running or self._blur_preview is not None:
            self._rebuild_pending = True
            return
        self._stop_rebuild_ui()
        self._set_series_interaction_enabled(False)
        self._rebuild_after_id = self.after_idle(self._rebuild_ui_on_main_thread)

    def _rebuild_ui_on_main_thread(self) -> None:
        self._rebuild_after_id = None
        if not self.winfo_exists():
            return
        if self._blur_running or self._blur_preview is not None:
            self._rebuild_pending = True
            return
        self._ui_rebuilding = True
        try:
            self._rebuild_ui()
        finally:
            self._ui_rebuilding = False
            self._set_series_interaction_enabled(True)

    def _destroy_ui(self) -> None:
        """Remove Series View widgets while keeping loaded series data in memory."""
        self._blur_running = False
        self._stop_blur_worker_poll()
        self._release_blur_review_state()
        viewer = getattr(self, "image_viewer", None)
        if viewer is not None:
            self._release_image_viewer(viewer, destroy_widget=True)
            self.image_viewer = None  # type: ignore[assignment]
        if hasattr(self, "_sv_frame") and self._sv_frame is not None:
            with contextlib.suppress(tk.TclError):
                self.update_idletasks()
                self._sv_frame.destroy()
            self._sv_frame = None

    def _rebuild_ui(self) -> None:
        """Rebuild Series View widgets and restore the initial single-pane layout."""
        if self._frames is None or self._ds is None:
            return

        whitelist_items = self._capture_whitelist_items()

        self._remember_dicom_wl_ww()
        self.update_idletasks()
        self._destroy_ui()
        self.update_idletasks()
        self._build_ui()
        self._restore_whitelist_items(whitelist_items)

        self._update_title()
        self.deiconify()
        self.lift()
        self._apply_initial_viewer_display()
        self._refresh_analysis_cache_ui()

    def _build_ui(self) -> None:
        assert self._ds is not None and self._frames is not None

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # SeriesView Frame:
        self._sv_frame = ctk.CTkFrame(self)
        self._sv_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self._sv_frame.grid_rowconfigure(0, weight=1)
        self._sv_frame.grid_columnconfigure(1, weight=1)

        # Whitelist frame:
        whitelist_frame = ctk.CTkFrame(self._sv_frame)
        whitelist_frame.grid(row=0, column=0, sticky="nsew", padx=self.PAD, pady=self.PAD)
        whitelist_frame.grid_columnconfigure(2, weight=1)
        whitelist_frame.grid_rowconfigure(3, weight=1)

        # Whitelist buttons:
        whitelist_title = ctk.CTkLabel(whitelist_frame, text=_("WHITE LIST"))
        whitelist_title.grid(row=0, columnspan=2, sticky="ew")
        whitelist_defaults_button = ctk.CTkButton(
            whitelist_frame, text=_("Defaults"), command=self.whitelist_defaults_button_clicked
        )
        whitelist_defaults_button.grid(row=1, column=0, sticky="ew", padx=self.PAD, pady=self.PAD)
        whitelist_clear_button = ctk.CTkButton(whitelist_frame, text=_("Clear"), command=self.clear_whitelist)
        whitelist_clear_button.grid(row=1, column=1, sticky="ew", padx=(0, self.PAD), pady=self.PAD)

        # Whitelist entry:
        self.whitelist_entry = ctk.CTkEntry(whitelist_frame)
        self.whitelist_entry.bind("<Return>", self.whitelist_button_clicked_or_entry_return)
        self.whitelist_entry.grid(row=2, columnspan=3, sticky="ew")

        scrollbar = ctk.CTkScrollbar(whitelist_frame, orientation="vertical")
        self.whitelist = tk.Listbox(
            whitelist_frame,
            border=0,
            yscrollcommand=scrollbar.set,
            bg="black",
            selectbackground="#004080",
            fg="white",
            selectforeground="white",
            highlightthickness=0,  # Remove focus highlight border
            activestyle="none",  # Remove underline on active item
        )
        scrollbar.configure(command=self.whitelist.yview)
        self.whitelist.bind("<Delete>", self.whitelist_delete_keypressed)
        self.whitelist.bind("<BackSpace>", self.whitelist_delete_keypressed)
        self.whitelist.grid(row=3, columnspan=2, sticky="nsew")
        scrollbar.grid(row=3, column=2, sticky="ns")

        # ImageViewer:
        self.image_viewer = ImageViewer(
            self._sv_frame,
            self._frames,
            *self._viewer_wl_ww(),
            add_to_whitelist_callback=self.add_to_whitelist,
            regenerate_series_projections_callback=self.regenerate_series_projections,
        )
        self.image_viewer.grid(row=0, column=1, sticky="nsew")
        self.image_viewer.detach_companion_stack()
        self._blur_review_saved = None
        self._blur_preview = None
        self._blur_worker_queue = queue.Queue()
        self._blur_running = False

        # Control Frame (two toolbar rows + status line):
        self.control_frame = ctk.CTkFrame(self._sv_frame)
        self.control_frame.grid(row=1, columnspan=2, sticky="ew", padx=self.PAD, pady=self.PAD)
        self.control_frame.grid_columnconfigure(1, weight=1)

        text_edit_group = ctk.CTkFrame(self.control_frame, fg_color="transparent")
        text_edit_group.grid(row=0, column=0, padx=(0, self.PAD), pady=self.PAD, sticky="w")
        edit_context_label = ctk.CTkLabel(text_edit_group, text=_("Text Edit Context") + ":")
        edit_context_label.grid(row=0, column=0, padx=(self.PAD, 2))
        self.edit_context_combo_box = ctk.CTkComboBox(
            text_edit_group,
            state="readonly",
            values=[
                member.value.upper()
                for member in EditContext
                if not (self.single_frame and member == EditContext.SERIES)
            ],
            command=self.edit_context_change,
        )
        self.edit_context_combo_box.set(EditContext.FRAME.upper())
        self.edit_context_combo_box.grid(row=0, column=1, padx=(0, 8))
        self.detect_button = ctk.CTkButton(
            text_edit_group, width=self.BUTTON_WIDTH, text=_("Detect Text"), command=self.detect_text_button_clicked
        )
        self.detect_button.grid(row=0, column=2, padx=(0, 2), pady=0)
        self.remove_button = ctk.CTkButton(
            text_edit_group, width=self.BUTTON_WIDTH, text=_("Remove Text"), command=self.remove_text_button_clicked
        )
        self.remove_button.grid(row=0, column=3, padx=2, pady=0)
        self.blackout_button = ctk.CTkButton(
            text_edit_group, width=self.BUTTON_WIDTH, text=_("Blackout Area"), command=self.blackout_button_clicked
        )
        self.blackout_button.grid(row=0, column=4, padx=(2, self.PAD), pady=0)

        harmonize_blur_group = ctk.CTkFrame(self.control_frame, fg_color="transparent")
        harmonize_blur_group.grid(row=1, column=0, padx=(0, self.PAD), pady=(0, self.PAD), sticky="w")
        harmonize_state = self._harmonize_button_state()
        self.harmonize_button = ctk.CTkButton(
            harmonize_blur_group,
            width=160,
            text=_("Harmonize Description"),
            command=self.harmonize_description_button_clicked,
            state=harmonize_state,
        )
        self.harmonize_button.grid(row=0, column=0, padx=(self.PAD, 2), pady=0, sticky="w")
        self.blur_face_button = ctk.CTkButton(
            harmonize_blur_group,
            width=120,
            text=_("Blur Face"),
            command=self.blur_face_button_clicked,
            state="disabled",
        )
        self.blur_face_button.grid(row=0, column=1, padx=2, pady=0, sticky="w")
        self.blur_face_mode_var = tk.StringVar(value=face_blur_mode_menu_values()[0])
        self.blur_face_mode_menu = ctk.CTkOptionMenu(
            harmonize_blur_group,
            width=140,
            values=face_blur_mode_menu_values(),
            variable=self.blur_face_mode_var,
        )
        self.blur_face_mode_menu.grid(row=0, column=2, padx=(2, 2), pady=0, sticky="w")
        self.clear_ts_cache_button = ctk.CTkButton(
            harmonize_blur_group,
            width=130,
            text=_("Clear TS Cache"),
            command=self.clear_ts_cache_button_clicked,
            state=self._clear_ts_cache_button_state(),
        )
        self.clear_ts_cache_button.grid(row=0, column=3, padx=(2, self.PAD), pady=0, sticky="w")

        self.save_button = ctk.CTkButton(
            self.control_frame,
            width=130,
            text=_("Save Pixel Changes"),
            command=self.save_series_button_clicked,
        )
        self.save_button.grid(row=1, column=1, padx=self.PAD, pady=(0, self.PAD), sticky="e")
        self.save_button.configure(state="disabled")

        self._status_label = ctk.CTkLabel(
            self.control_frame,
            text="",
            anchor="w",
            justify="left",
            wraplength=self.STATUS_WRAPLENGTH,
        )
        self._status_label.grid(
            row=2,
            column=0,
            columnspan=2,
            padx=self.PAD,
            pady=(0, self.PAD),
            sticky="w",
        )
        self._show_default_context_line()

        self._refresh_blur_face_ui()

        try:
            whitelist = load_project_whitelist(self._series_path.parents[3], self._ds.Modality)
            for item in whitelist:
                self.whitelist.insert(tk.END, item)
        except Exception:
            self.load_whitelist_defaults()

    def load_frames(self, series_path: Path) -> tuple[Dataset, np.ndarray, tuple[Path, ...]]:
        """Loads, processes, and combines series frames and projections."""
        ds, frames, slice_paths, _geometry = self._load_series_data(series_path)
        return ds, frames, slice_paths

    def _update_title(self):
        title = _("Series View")
        if self._ds:
            phi = self._anon_model.get_phi_by_anon_patient_id(self._ds.PatientID)
            if phi:
                title += (
                    f" for {phi.patient_name} PHI ID:{phi.patient_id} ANON ID: {self._ds.PatientID}"
                    + f" {self._ds.get('SeriesDescription', '')} "
                )
        self.title(title)

    def _series_context_line(self) -> str:
        geometry = self._ensure_series_geometry()
        if geometry is None:
            return ""
        return format_series_view_geometry_line(geometry)

    def _show_default_context_line(self) -> None:
        if hasattr(self, "_status_label"):
            self._status_label.configure(text=self._series_context_line())

    def update_status(self, message: str) -> None:
        """Overwrite the context line with transient operation status."""
        logger.info("Series view: %s", message)
        if hasattr(self, "_status_label"):
            self._status_label.configure(text=message)

    def _harmonize_button_state(self) -> str:
        if getattr(self._ds, "Modality", None) != "CT":
            return "disabled"
        if series_description_is_harmonized(self._series_path, self._ds) is True:
            return "disabled"
        return "normal"

    def _refresh_harmonize_button(self) -> None:
        if not hasattr(self, "harmonize_button"):
            return
        self.harmonize_button.configure(state=self._harmonize_button_state())

    def _clear_ts_cache_button_state(self) -> str:
        if getattr(self._ds, "Modality", None) != "CT":
            return "disabled"
        if tseg_cache_summary(self._series_path).exists:
            return "normal"
        return "disabled"

    def _refresh_clear_ts_cache_button(self) -> None:
        if not hasattr(self, "clear_ts_cache_button"):
            return
        self.clear_ts_cache_button.configure(state=self._clear_ts_cache_button_state())

    def _refresh_analysis_cache_ui(self) -> None:
        self._refresh_harmonize_button()
        self._refresh_blur_face_ui()
        self._refresh_clear_ts_cache_button()
        self._show_default_context_line()

    def _on_series_description_updated(self) -> None:
        self._update_title()
        self._refresh_harmonize_button()
        self._show_default_context_line()

    def _face_blur_eligibility(self) -> FaceBlurEligibility:
        geometry = self._ensure_series_geometry()
        if (
            self._face_blur_eligibility_cache is not None
            and geometry is self._face_blur_eligibility_geometry
        ):
            return self._face_blur_eligibility_cache

        eligibility = evaluate_face_blur_eligibility(
            self._series_path,
            ds=self._ds,
            geometry=geometry,
            enable_tseg_face=ENABLE_TSEG_FACE,
        )
        self._face_blur_eligibility_cache = eligibility
        self._face_blur_eligibility_geometry = geometry
        return eligibility

    def _refresh_blur_face_ui(self) -> None:
        eligibility = self._face_blur_eligibility()
        state = "disabled" if eligibility.decision == FaceBlurGateDecision.BLOCK else "normal"
        if not self._blur_running and self._blur_preview is None:
            if hasattr(self, "blur_face_button"):
                self.blur_face_button.configure(state=state)
            if hasattr(self, "blur_face_mode_menu"):
                self.blur_face_mode_menu.configure(state=state)

    def _selected_face_blur_mode(self) -> FaceBlurMode:
        if not hasattr(self, "blur_face_mode_var"):
            return FaceBlurMode.GAUSSIAN
        return face_blur_mode_from_menu_label(self.blur_face_mode_var.get())

    def _blur_face_button_state(self) -> str:
        eligibility = self._face_blur_eligibility()
        if eligibility.decision == FaceBlurGateDecision.BLOCK:
            return "disabled"
        return "normal"

    def clear_whitelist(self):
        logger.info("Clearing whitelist")
        self.whitelist.delete(0, "end")
        self.whitelist_entry.delete(0, ctk.END)
        self.whitelist_entry.focus_set()

    def add_to_whitelist(self, text: str):
        whitelist = self.whitelist.get(0, tk.END)
        try:
            ndx = whitelist.index(text)
            # Already in whitelist, hightlight:
            self.whitelist.select_set(ndx)
        except ValueError:
            # Not in whitelist, insert:
            logger.info(f"Adding to whitelist: {text}")
            self.whitelist.insert(0, text)
            self._whitelist_changed = True

    def insert_entry_into_whitelist(self):
        new_item = self.whitelist_entry.get()
        if new_item == "":
            return
        self.add_to_whitelist(new_item)
        self.whitelist_entry.delete(0, ctk.END)

    def get_whitelist_set(self) -> list[str]:
        return [item.upper().strip() for item in self.whitelist.get(0, "end") if item.strip()]

    def whitelist_button_clicked_or_entry_return(self, event):
        self.insert_entry_into_whitelist()

    def whitelist_delete_keypressed(self, event):
        selected_indices = self.whitelist.curselection()

        if not selected_indices:  # Check if anything is selected
            return

        # Delete items in reverse order to avoid index issues.
        for i in reversed(selected_indices):
            self.whitelist.delete(i)
            self.whitelist.select_set(i - 1)
            self.whitelist.activate(i - 1)

        self._whitelist_changed = True

    def edit_context_change(self, choice):
        logger.info(f"Edit Context changed to: {choice}")
        self.edit_context = EditContext[choice]
        self.image_viewer.set_overlay_propagation(self.edit_context == EditContext.SERIES)

    def regenerate_series_projections(self):
        if self._frames is not None and not self.single_frame:
            logger.info("Regenerate Series Projections")
            self._frames[0] = np.min(self._frames, axis=0)
            self._frames[1] = np.mean(self._frames, axis=0).astype(self._frames.dtype)
            self._frames[2] = np.max(self._frames, axis=0)

    def initialise_ocr(self):
        # Once-off initialisation of easyocr.Reader (and underlying pytorch model):
        # if pytorch models not downloaded yet, they will be when Reader initializes
        logging.info("OCR Reader initialising...")

        model_dir = Path("assets") / "ocr" / "model"  # Default is: Path("~/.EasyOCR/model").expanduser()
        if not model_dir.exists():
            # TODO: notify user via status bar or messagebox
            logger.warning(
                f"EasyOCR model directory: {model_dir}, does not exist, EasyOCR will create it, models still to be downloaded..."
            )
        else:
            logger.info(f"EasyOCR downloaded models: {os.listdir(model_dir)}")

        # Initialize the EasyOCR reader with the desired language(s), if models are not in model_dir, they will be downloaded
        # TODO: use thread for this if models not downloaded yet, provide status updates during download:
        # TODO: optimize so reader is only initialised once - reference passed by ProjectionView or IndexView or global?
        self._ocr_reader = Reader(
            lang_list=["en", "de", "fr", "es"],
            gpu=True,
            model_storage_directory=model_dir,
            verbose=True,
        )

        logging.info("OCR Reader initialised successfully")

    def filter_text_data(self, frame_index: int, similarity_threshold: float = 0.75) -> list[OCRText]:
        """
        Filters the text_data for a frame based on fuzzy matching against the whitelist.
        Keeps text if its similarity threshold to ALL whitelist items is <= 0.75.
        # TODO: provide UX to modify similarity threshold
        """
        # Use unfiltered_text_data which stores the raw OCR results
        if frame_index not in self.detected_text:
            return []

        # Preprocess whitelist items once
        whitelist_set = self.get_whitelist_set()
        if not whitelist_set:  # If whitelist is empty, return all results
            return self.detected_text.get(frame_index, [])

        filtered_results = []
        for ocr_text in self.detected_text[frame_index]:
            if not ocr_text.text:  # Skip if OCR text is empty
                continue

            processed_ocr_text = ocr_text.text.upper().strip()
            is_similar_to_whitelist = False

            # Check similarity against each whitelist item
            for whitelist_item in whitelist_set:
                # Use SequenceMatcher to get the similarity ratio
                similarity = difflib.SequenceMatcher(None, processed_ocr_text, whitelist_item).ratio()

                if similarity > similarity_threshold:
                    is_similar_to_whitelist = True
                    logger.debug(
                        f"'{ocr_text.text}' matched whitelist item '{whitelist_item}' "
                        f"with similarity ratio {similarity:.2f}. Filtering out."
                    )
                    break  # Found a close match, no need to check further

            # Keep the text only if it wasn't similar to any whitelist item
            if not is_similar_to_whitelist:
                filtered_results.append(ocr_text)

        return filtered_results

    def draw_text_overlay(self, frame_index: int):
        """Draws text boxes on the overlay for the given frame, based on filtered text_data."""
        filtered_text_data = self.filter_text_data(frame_index)  # Filter *before* drawing
        self.image_viewer.set_text_overlay_data(frame_index, filtered_text_data)

    def process_single_frame_ocr(self, frame_index: int):
        """Performs OCR on a single frame, filters, and stores results."""
        with torch.no_grad():
            if self._ocr_reader:
                results = detect_text(
                    pixels=apply_windowing(
                        self.image_viewer.current_wl,
                        self.image_viewer.current_ww,
                        self.image_viewer.images[frame_index],
                    ),
                    ocr_reader=self._ocr_reader,
                    draw_boxes_and_text=False,
                )
                if results:
                    logger.debug(f"OCR Results:\n{pformat(results)}")
                    self.detected_text[frame_index] = results
                    self.draw_text_overlay(frame_index)

    def detect_text_for_series(self):
        """Detects text in all frames of the series."""
        total_frames = self.image_viewer.num_images
        self.update_status(_("Detecting text in all images") + "…")
        for i in range(total_frames):
            self.image_viewer.load_and_display_image(i)  # Goto series start
            self.process_single_frame_ocr(i)
            self.update_status(_("Detecting text") + f"… {_('image')} {i + 1} {_('of')} {total_frames}")

    def detect_text_button_clicked(self):
        logger.info("Detecting text...")

        if self._ocr_reader is None:
            self.initialise_ocr()

        # Check if GPU available
        logger.info(f"Apple MPS (Metal) GPU Available: {torch.backends.mps.is_available()}")
        logger.info(f"CUDA GPU Available: {torch.cuda.is_available()}")

        if self.edit_context == EditContext.FRAME:
            self.update_status(_("Detecting text in current image") + "…")
            self.process_single_frame_ocr(self.image_viewer.current_image_index)
            self.update_status(_("Text detection complete"))
        else:
            self.detect_text_for_series()
            self.update_status(_("Text detection complete"))

        # TODO: work out what to do beyond propagting edits in overlays when edit context is PROJECT

        gc.collect()
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()

    def remove_text_from_single_frame(self, frame_index: int, ocr_texts: list[OCRText]):
        logger.debug(f"Remove {len(ocr_texts)} words from frame {frame_index}")
        raw_frame = self.image_viewer.images[frame_index]
        windowed_frame = apply_windowing(self.image_viewer.current_wl, self.image_viewer.current_ww, raw_frame)
        self.image_viewer.images[frame_index] = remove_text(raw_frame, windowed_frame, ocr_texts)
        self.save_button.configure(state="enabled")
        ocr_texts.clear()

    def remove_text_from_series(self):
        total_frames = self.image_viewer.num_images
        self.image_viewer.clear_cache()
        for i in range(total_frames):
            if i in self.image_viewer.overlay_data:
                ocr_texts = self.image_viewer.overlay_data[i].ocr_texts
                if ocr_texts:
                    self.remove_text_from_single_frame(i, ocr_texts)
                self.image_viewer.load_and_display_image(i)
                self.update()
        self.image_viewer.clear_cache()
        self.regenerate_series_projections()
        self.image_viewer.load_and_display_image(0)

    def remove_text_button_clicked(self):
        logger.debug(f"Removing text, current edit context={self.edit_context}")

        if self._ocr_reader is None:
            self.initialise_ocr()

        if self.edit_context == EditContext.FRAME:
            ndx = self.image_viewer.current_image_index
            ocr_texts = self.image_viewer.overlay_data[ndx].ocr_texts
            if not ocr_texts:
                logger.warning("No text has been detected in current frame to remove")
                self.update_status(_("No text detected in current frame to remove"))
                return
            self.update_status(_("Removing text from current image") + "…")
            self.remove_text_from_single_frame(ndx, ocr_texts)
            self.update_status(_("Text removed from current image"))
            self.image_viewer.refresh_current_image()
        else:
            self.update_status(_("Removing text from all images") + "…")
            self.remove_text_from_series()
            self.update_status(_("Text removed from all images"))

        # TODO: Remove all in PROJECT if modality and image size constant

    def blackout_areas_in_single_frame(self, frame_index: int, user_rects: list[UserRectangle]):
        logger.debug(f"Blackout {len(user_rects)} rects from frame {frame_index}")
        blackout_rectangular_areas(self.image_viewer.images[frame_index], user_rects)
        self.save_button.configure(state="enabled")
        user_rects.clear()

    def blackout_areas_in_series(self):
        total_frames = self.image_viewer.num_images
        self.image_viewer.clear_cache()
        for i in range(total_frames):
            if i not in self.image_viewer.overlay_data:
                continue
            user_rects = self.image_viewer.overlay_data[i].user_rects
            if user_rects:
                self.blackout_areas_in_single_frame(i, user_rects)
            self.image_viewer.load_and_display_image(i)
            self.update()
        self.image_viewer.clear_cache()
        self.regenerate_series_projections()
        self.image_viewer.load_and_display_image(0)

    def blackout_button_clicked(self):
        logger.debug(f"Blackout text, current edit context[{self.edit_context}]")

        if self.edit_context == EditContext.FRAME:
            ndx = self.image_viewer.current_image_index
            user_rects = self.image_viewer.overlay_data[ndx].user_rects
            if not user_rects:
                logger.warning("No blackout user rect has been define in current frame to blackout")
                self.update_status(_("No blackout area(s) in current frame"))
                return
            self.update_status(_("Applying blackout to current image") + "…")
            self.blackout_areas_in_single_frame(ndx, user_rects)
            if not self.single_frame:
                self.image_viewer.clear_cache()
                self.regenerate_series_projections()
            self.update_status(_("Blackout applied to current image"))
            self.image_viewer.refresh_current_image()
        else:
            self.update_status(_("Applying blackout to all images") + "…")
            self.blackout_areas_in_series()
            self.update_status(_("Blackout applied to all images"))

    def harmonize_description_button_clicked(self):
        if self._ds is None or getattr(self._ds, "Modality", None) != "CT":
            return

        logger.info("Harmonize starting for %s", self._series_path)
        self.harmonize_button.configure(state="disabled")
        mono_font = getattr(self.master, "_data_font", None)
        show_harmonize_results_view(
            self,
            series_path=self._series_path,
            ds=self._ds,
            current_description=str(self._ds.get("SeriesDescription", "") or "").strip(),
            mono_font=mono_font,
            anon_model=self._anon_model,
            on_series_description_updated=self._on_series_description_updated,
        )
        self._face_blur_eligibility_cache = None
        self._face_blur_eligibility_geometry = None
        self._refresh_analysis_cache_ui()

    def clear_ts_cache_button_clicked(self) -> None:
        if self._ds is None or getattr(self._ds, "Modality", None) != "CT":
            return

        summary = tseg_cache_summary(self._series_path)
        if not summary.exists:
            return

        size_mb = summary.size_bytes / (1024 * 1024)
        size_text = f"{size_mb:.1f} MB" if size_mb >= 0.1 else _("< 0.1 MB")

        confirmed = messagebox.askyesno(
            title=_("Clear Analysis Cache"),
            message=(
                _("Delete analysis cache for this series?")
                + "\n\n"
                + _("Removes geometry, segmentation masks, contrast analysis, and face mask under")
                + f" {TSEG_CACHE_DIRNAME}/ ({size_text}, {summary.file_count} "
                + _("files")
                + ").\n\n"
                + _("DICOM images and series description are not changed.")
                + "\n\n"
                + _("Next Harmonize or Blur Face will re-run analysis and may take several minutes.")
            ),
            parent=self,
            default="no",
        )
        if not confirmed:
            return

        logger.info("Clearing TS cache for %s", self._series_path)
        clear_tseg_series_cache(self._series_path)
        self._series_geometry = None
        self._face_blur_eligibility_cache = None
        self._face_blur_eligibility_geometry = None
        self._schedule_rebuild_ui()
        self.update_status(_("Analysis cache cleared"))

    def _teardown_blur_review(
        self,
        *,
        keep_applied_frames: bool = False,
        restore_dicom_wl: bool = False,
    ) -> None:
        self._log_series_memory("blur_review_teardown_start", array=self._frames)
        viewer = self.image_viewer
        saved = self._blur_review_saved
        viewer._resize_to_viewport_enabled = False
        viewer.detach_companion_stack()

        if saved is not None:
            if keep_applied_frames and self._frames is not None:
                viewer.images = self._frames
                viewer.num_images = self._frames.shape[0]
                viewer.image_height = self._frames.shape[1]
                viewer.image_width = self._frames.shape[2]
                viewer.small_jump = max(1, int(viewer.num_images * viewer.SMALL_JUMP_PERCENTAGE))
                viewer.large_jump = max(1, int(viewer.num_images * viewer.LARGE_JUMP_PERCENTAGE))
            elif not keep_applied_frames:
                viewer.images = saved["images"]  # type: ignore[assignment]
                viewer.num_images = int(saved["num_images"])  # type: ignore[arg-type]
                viewer.image_height = int(saved["image_height"])  # type: ignore[arg-type]
                viewer.image_width = int(saved["image_width"])  # type: ignore[arg-type]
                viewer.small_jump = int(saved["small_jump"])  # type: ignore[arg-type]
                viewer.large_jump = int(saved["large_jump"])  # type: ignore[arg-type]

            viewer.overlay_data = saved["overlay_data"]  # type: ignore[assignment]
            viewer.active_layers = set(saved["active_layers"])  # type: ignore[arg-type]
            viewer.active_layers.discard(LayerType.SEGMENTATIONS)
            viewer.segmentation_overlay_color = saved["segmentation_overlay_color"]  # type: ignore[assignment]
            viewer.segmentation_overlay_alpha = saved["segmentation_overlay_alpha"]  # type: ignore[assignment]
            if self._ds is not None:
                if restore_dicom_wl or not keep_applied_frames:
                    wl, ww = self._dicom_wl_ww()
                else:
                    wl, ww = face_review_wl_ww(self._ds)
                viewer.set_wlww_sync(wl, ww)

            saved_index = int(saved["current_image_index"])
            if keep_applied_frames and not self.single_frame:
                restore_index = min(saved_index + 3, viewer.num_images - 1)
            else:
                restore_index = min(saved_index, viewer.num_images - 1)
            viewer.clear_cache()
            viewer.current_image_index = restore_index
        self._blur_review_saved = None
        self._blur_preview = None
        self._apply_initial_viewer_display()
        self._log_series_memory("blur_review_teardown_done", array=self._frames)
        self._refresh_blur_face_ui()
        self._flush_pending_rebuild_ui()

    def _show_blur_review(self, preview: FaceBlurPreviewResult) -> None:
        if self._frames is None or self._ds is None:
            return

        self._blur_preview = preview
        self._log_series_memory("blur_review_show", array=preview.blurred_slice_frames)
        viewer = self.image_viewer
        if viewer.playing:
            viewer.toggle_play()

        slice_stack = self._slice_stack()
        blurred_frames = preview.blurred_slice_frames
        if blurred_frames is None:
            if preview.hu_after is None:
                return
            blurred_frames = hu_stack_to_viewer_frames(
                preview.hu_after,
                preview.slice_paths,
                reference_ds=self._ds,
                frame_dtype=slice_stack.dtype,
            )

        self._blur_review_saved = {
            "images": viewer.images,
            "num_images": viewer.num_images,
            "image_height": viewer.image_height,
            "image_width": viewer.image_width,
            "small_jump": viewer.small_jump,
            "large_jump": viewer.large_jump,
            "overlay_data": viewer.overlay_data.copy(),
            "active_layers": viewer.active_layers.copy(),
            "segmentation_overlay_color": viewer.segmentation_overlay_color,
            "segmentation_overlay_alpha": viewer.segmentation_overlay_alpha,
            "current_image_index": viewer.current_image_index,
        }

        viewer._resize_to_viewport_enabled = False
        viewer.clear_cache()
        viewer.current_image_index = 0
        viewer.images = slice_stack.copy()
        viewer.num_images = slice_stack.shape[0]
        viewer.image_height = slice_stack.shape[1]
        viewer.image_width = slice_stack.shape[2]
        viewer.small_jump = max(1, int(viewer.num_images * viewer.SMALL_JUMP_PERCENTAGE))
        viewer.large_jump = max(1, int(viewer.num_images * viewer.LARGE_JUMP_PERCENTAGE))
        viewer.overlay_data.clear()
        viewer.active_layers.discard(LayerType.TEXT)
        viewer.active_layers.discard(LayerType.USER_RECT)
        viewer.active_layers.add(LayerType.SEGMENTATIONS)
        viewer.segmentation_overlay_color = FACE_MASK_OVERLAY_COLOR
        viewer.segmentation_overlay_alpha = FACE_MASK_OVERLAY_ALPHA

        segmentations_by_slice: dict[int, list] = {}
        for slice_index in range(preview.mask.shape[0]):
            segmentations = mask_slice_segmentations(preview.mask, slice_index)
            if segmentations:
                segmentations_by_slice[slice_index] = segmentations
        viewer.set_segmentation_overlays(segmentations_by_slice)

        review_wl, review_ww = face_review_wl_ww(self._ds)
        viewer.attach_companion_stack(
            blurred_frames,
            primary_label=_("Current — face region (green)"),
            companion_label=_("Proposed face blur"),
        )
        viewer.set_wlww_sync(review_wl, review_ww)
        self.update_idletasks()
        viewer._resize_to_viewport_enabled = True
        viewer._set_initial_size()

        qa_summary = format_face_blur_qa_summary(
            preview.qa_stats,
            sigma_mm=preview.sigma_mm,
            slice_count=preview.slice_count,
            blur_mode=preview.blur_mode,
        )
        self.update_status(
            qa_summary + " " + _("Review side-by-side, then Save Pixel Changes to keep.")
        )
        self.save_button.configure(state="normal")
        self.blur_face_button.configure(state="disabled")
        if hasattr(self, "blur_face_mode_menu"):
            self.blur_face_mode_menu.configure(state="disabled")
        self._refresh_blur_face_ui()

    def _blur_worker(self, blur_mode, volume_context: SeriesVolumeContext) -> None:
        def on_progress(progress) -> None:
            self._blur_worker_queue.put(("progress", progress))

        try:
            preview = preview_face_blur(
                self._series_path,
                progress=on_progress,
                volume_context=volume_context,
                blur_mode=blur_mode,
            )
            self._blur_worker_queue.put(("done", preview))
        except Exception as exc:
            logger.exception("Face blur preview worker failed for %s", self._series_path)
            self._blur_worker_queue.put(("error", exc))

    def _launch_blur_worker(self, blur_mode: FaceBlurMode) -> None:
        """Start the blur worker after UI lockout has settled on the main thread."""
        if not self._blur_running or not self.winfo_exists():
            return
        if self._frames is None or self._ds is None:
            self._blur_running = False
            self._set_series_interaction_enabled(True)
            return

        geometry = self._ensure_series_geometry()
        volume_context = SeriesVolumeContext(
            reference_ds=copy.deepcopy(self._ds),
            slice_frames=self._slice_stack().copy(),
            slice_paths=self._slice_paths,
            slice_spacing_mm=geometry.slice_spacing_mm if geometry is not None else None,
        )
        threading.Thread(
            target=self._blur_worker,
            args=(blur_mode, volume_context),
            name="BlurFacePreviewWorker",
            daemon=True,
        ).start()
        self._blur_poll_after_id = self.after(self.BLUR_POLL_MS, self._poll_blur_worker)

    def _complete_blur_review(self, preview: FaceBlurPreviewResult) -> None:
        """Show blur review on an idle tick, avoiding CTk churn during poll callbacks."""
        self._blur_review_after_id = None
        if not self.winfo_exists() or not self._blur_running:
            return
        if self._ui_rebuilding:
            self._blur_review_after_id = self.after_idle(
                lambda p=preview: self._complete_blur_review(p)
            )
            return

        try:
            self._show_blur_review(preview)
        finally:
            self._blur_running = False
            self._set_series_interaction_enabled(True)
            self._refresh_blur_face_ui()
            self._flush_pending_rebuild_ui()

    def _poll_blur_worker(self) -> None:
        if not self.winfo_exists():
            return

        while True:
            try:
                kind, payload = self._blur_worker_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "progress":
                if self._blur_running:
                    self.update_status(format_face_blur_progress_status(payload))
            elif kind == "done":
                if not self._blur_running:
                    continue
                preview = payload
                if preview.error is not None:
                    self._blur_running = False
                    messagebox.showerror(
                        title=_("Blur Face"),
                        message=preview.error,
                        parent=self,
                    )
                    self.update_status(_("Could not blur facial features"))
                    self._set_series_interaction_enabled(True)
                    self._refresh_blur_face_ui()
                    self._flush_pending_rebuild_ui()
                    return
                self._stop_blur_review_deferred()
                self._blur_review_after_id = self.after_idle(
                    lambda p=preview: self._complete_blur_review(p)
                )
                return
            elif kind == "error":
                if not self._blur_running:
                    continue
                self._blur_running = False
                messagebox.showerror(
                    title=_("Blur Face"),
                    message=str(payload),
                    parent=self,
                )
                self.update_status(_("Could not blur facial features"))
                self._set_series_interaction_enabled(True)
                self._refresh_blur_face_ui()
                self._flush_pending_rebuild_ui()
                return

        if not self.winfo_exists():
            return
        self._blur_poll_after_id = self.after(self.BLUR_POLL_MS, self._poll_blur_worker)

    def _apply_face_blur_preview(self, preview: FaceBlurPreviewResult) -> None:
        """Merge accepted blur preview into in-memory frames (viewer rebuilt after save)."""
        if self._frames is None:
            return
        self._frames = apply_face_blur_preview_to_series_frames(
            self._frames,
            preview,
            single_frame=self.single_frame,
            reference_ds=self._ds,
            frame_dtype=self._slice_stack().dtype,
        )
        if not self.single_frame:
            self.regenerate_series_projections()
        self._face_blur_preview_pending = True

    def blur_face_button_clicked(self) -> None:
        if not self._series_interaction_allowed() or self._blur_running or self._blur_face_button_state() != "normal":
            return

        eligibility = self._face_blur_eligibility()
        if eligibility.decision == FaceBlurGateDecision.CONFIRM:
            proceed = messagebox.askyesno(
                title=_("Blur Face"),
                message=face_blur_gate_message(eligibility.reason),
                default="no",
                parent=self,
            )
            if not proceed:
                return
        elif eligibility.decision == FaceBlurGateDecision.BLOCK:
            messagebox.showinfo(
                title=_("Blur Face"),
                message=face_blur_gate_message(eligibility.reason),
                parent=self,
            )
            return

        logger.info(
            "Series View: blur face starting for %s (gate=%s)",
            self._series_path,
            eligibility.reason.name,
        )
        self._blur_running = True
        self._blur_worker_queue = queue.Queue()
        blur_mode = self._selected_face_blur_mode()
        self.update_status(_("Preparing face blur preview") + "…")
        self._set_series_interaction_enabled(False)
        self.after_idle(lambda: self._launch_blur_worker(blur_mode))

    def save_series_button_clicked(self):
        if self._frames is None or self._ds is None:
            logger.error("CRITICAL: No frames or dataset to save")
            return

        preview = self._blur_preview
        had_blur_review = preview is not None and preview.error is None
        if had_blur_review:
            if hasattr(self, "image_viewer"):
                with contextlib.suppress(tk.TclError):
                    self.image_viewer.detach_companion_stack()
            self._apply_face_blur_preview(preview)
            logger.info(
                "Series View: face blur applied on save for %s (slices=%d, qa=%s)",
                self._series_path,
                preview.slice_count,
                "PASS"
                if preview.qa_stats is None or preview.qa_stats.outside_clean
                else "FAIL",
            )

        # Save Whitelist:
        whitelist_set = self.get_whitelist_set()
        if self._whitelist_changed and whitelist_set:
            if not hasattr(self._ds, "Modality") or self._ds.Modality is None:
                logger.error("CRITICAL: Modality not found in dataset")
                return
            if len(self._series_path.parents) < 4:
                logger.error("CRITICAL: Series path does not have enough parents - cannot determine project directory")
                return
            try:
                whitelist_filepath = save_project_whitelist(
                    self._series_path.parents[3], self._ds.Modality, whitelist_set
                )
                logger.info(f"Saved whitelist to {whitelist_filepath}")
                self._whitelist_changed = False
            except Exception as e:
                logger.error(f"Error saving whitelist: {e}")

        if save_series_frames(self._series_path, self._frames if self.single_frame else self._frames[3:], self._ds):
            logger.info(f"Saved series frames to {self._series_path}")
            self._face_blur_preview_pending = False
            if had_blur_review and preview is not None:
                apply_series_face_blur_metadata(
                    self._anon_model,
                    str(self._ds.SeriesInstanceUID),
                    preview.blur_mode.value,
                )
            if hasattr(self, "image_viewer"):
                texts_by_frame = collect_series_view_pixel_phi_texts(self.image_viewer)
                if texts_by_frame:
                    projection_count = 0 if self.single_frame else 3
                    apply_series_view_pixel_phi(
                        self._anon_model,
                        self._slice_paths,
                        texts_by_frame,
                        projection_frame_count=projection_count,
                    )
            if had_blur_review:
                self._teardown_blur_review(keep_applied_frames=True, restore_dicom_wl=True)
                self.save_button.configure(state="disabled")
            else:
                self.save_button.configure(state="disabled")
            self.update_status(_("Changes saved"))
        else:
            logger.error(f"Failed to save series frames to {self._series_path}")
            messagebox.showerror(
                title=_("Save Changes Error"),
                message=_("Failed to save changes to series frames"),
                parent=self,
            )
            self.update_status(_("Could not save changes"))

    def whitelist_defaults_button_clicked(self):
        logger.info("Whitelist button clicked")
        self.clear_whitelist()
        self.load_whitelist_defaults()
        self._whitelist_changed = True

    def load_whitelist_defaults(self):
        # TODO: whitelist load error message to user
        if self._ds is None:
            logger.error("CRITICAL: self._ds is None")
            return
        if self._ds.Modality is None:
            logger.error("CRITICAL: Modality not found in dataset")
            return

        logger.info(f"Loading default whitelist for modality {self._ds.Modality}")

        try:
            whitelist = load_default_whitelist(self._ds.Modality)
        except FileNotFoundError:
            logger.error(f"Default whitelist for modality {self._ds.Modality} file not found")
            return
        except ValueError as e:
            logger.error(f"Error loading default whitelist for modality {self._ds.Modality}: {e}")
            return
        except Exception as e:
            logger.error(f"Unexpected error loading default whitelist for modality {self._ds.Modality}: {e}")
            return

        for item in whitelist:
            self.whitelist.insert(tk.END, item)

    def _escape_keypress(self, event):
        logger.info("_escape_pressed")
        self._on_cancel()

    def _log_series_memory(
        self,
        stage: str,
        *,
        array: np.ndarray | None = None,
        extra: str = "",
    ) -> float | None:
        parts = [self._series_path.name]
        if extra:
            parts.append(extra)
        return log_process_memory(stage, array=array, extra=" ".join(parts))

    def _log_close_memory(self, stage: str) -> float | None:
        return self._log_series_memory(f"close_{stage}", array=self._frames)

    def _log_series_data_size(self) -> None:
        total_bytes = 0
        parts: list[str] = []
        if self._frames is not None:
            total_bytes += self._frames.nbytes
            parts.append(f"_frames={self._frames.nbytes / (1024 * 1024):.1f}MB")
        preview = self._blur_preview
        if preview is not None:
            if preview.blurred_slice_frames is not None:
                total_bytes += preview.blurred_slice_frames.nbytes
                parts.append(f"blurred={preview.blurred_slice_frames.nbytes / (1024 * 1024):.1f}MB")
            total_bytes += preview.mask.nbytes
            parts.append(f"mask={preview.mask.nbytes / (1024 * 1024):.1f}MB")
        if self._blur_review_saved is not None:
            saved_images = self._blur_review_saved.get("images")
            if isinstance(saved_images, np.ndarray):
                total_bytes += saved_images.nbytes
                parts.append(f"review_saved={saved_images.nbytes / (1024 * 1024):.1f}MB")
        if total_bytes:
            logger.info(
                "SeriesView releasing %.1f MB of in-memory frame data (%s)",
                total_bytes / (1024 * 1024),
                ", ".join(parts),
            )

    @staticmethod
    def _drain_blur_worker_queue(worker_queue: queue.Queue[tuple[str, object]] | None = None) -> None:
        if worker_queue is None:
            return
        while True:
            try:
                worker_queue.get_nowait()
            except queue.Empty:
                return

    def _release_blur_review_state(self) -> None:
        """Drop blur-review references without restoring viewer layout (used on window close)."""
        self._blur_review_saved = None
        self._blur_preview = None
        if hasattr(self, "_blur_worker_queue"):
            self._drain_blur_worker_queue(self._blur_worker_queue)
        if hasattr(self, "image_viewer"):
            with contextlib.suppress(tk.TclError):
                self.image_viewer.detach_companion_stack()

    def _release_image_viewer(
        self,
        viewer: ImageViewer | None,
        *,
        destroy_widget: bool = False,
    ) -> None:
        if viewer is None:
            return
        try:
            if destroy_widget:
                viewer.destroy()
            else:
                viewer.release_resources()
        except tk.TclError:
            logger.debug("ImageViewer already destroyed during SeriesView close")
            return

    def _release_all_viewer_resources(self) -> None:
        if hasattr(self, "image_viewer"):
            self._release_image_viewer(self.image_viewer)

    def _release_series_data(self) -> None:
        self._blur_preview = None
        self._blur_review_saved = None
        self._frames = None
        self._slice_paths = ()
        self._ds = None
        self._series_geometry = None
        self.detected_text.clear()

    def _release_ocr_reader(self) -> None:
        if self._ocr_reader is None:
            return
        del self._ocr_reader
        self._ocr_reader = None
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
        elif torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _on_cancel(self):
        logger.info("_on_cancel")
        self._blur_running = False
        self._stop_blur_worker_poll()
        self._stop_blur_review_deferred()
        self._stop_rebuild_ui()
        if self._loading:
            self._loading = False
            self._stop_load_progress_pulse()
            with contextlib.suppress(tk.TclError):
                self.grab_release()
            self.destroy()
            return

        rss_before = self._log_close_memory("before")
        self._log_series_data_size()

        self._release_blur_review_state()
        self._release_all_viewer_resources()
        self._release_series_data()
        self._release_ocr_reader()

        with contextlib.suppress(tk.TclError):
            self.grab_release()

        self.destroy()
        gc.collect()
        gc.collect()

        rss_after = self._log_close_memory("after")
        if rss_before is not None and rss_after is not None:
            logger.info(
                "SeriesView close memory delta: %.1f MB (before %.1f MB, after %.1f MB)",
                rss_before - rss_after,
                rss_before,
                rss_after,
            )
