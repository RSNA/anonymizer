import contextlib
import gc
import logging
import queue
import threading
import tkinter as tk
from enum import StrEnum, auto
from pathlib import Path
from pprint import pformat
from tkinter import messagebox

import customtkinter as ctk
import numpy as np
from pydicom import Dataset, dcmread

from anonymizer.controller.blur_face import (
    FaceBlurEligibility,
    FaceBlurGateDecision,
    FaceBlurGateReason,
    FaceBlurMode,
    evaluate_face_blur_eligibility,
    face_blur_gate_message,
    face_blur_status_applicable,
)
from anonymizer.controller.create_projections import (
    apply_windowing,
    get_wl_ww,
    load_series_frames,
    save_series_frames,
)
from anonymizer.controller.remove_pixel_phi import (
    OcrService,
    OCRText,
    UserRectangle,
    apply_series_view_pixel_phi,
    blackout_rectangular_areas,
    collect_series_view_pixel_phi_texts,
    filter_ocr_detections,
    remove_text,
)
from anonymizer.controller.tseg.cache import clear_series_tseg_cache, tseg_cache_summary
from anonymizer.controller.tseg.config import TSEG_CACHE_DIRNAME
from anonymizer.controller.tseg.dicom_geometry import (
    SeriesGeometryResult,
    ensure_series_geometry,
    format_series_view_geometry_line,
    load_geometry_cache,
    stackable_dicom_paths,
)
from anonymizer.controller.tseg.runtime_status import face_blur_allowed, get_ai_session, harmonize_allowed
from anonymizer.model.anonymizer import AnonymizerModel, format_series_processing_status
from anonymizer.model.project import ProjectModel
from anonymizer.utils.memory import log_process_memory
from anonymizer.utils.storage import (
    get_dcm_files,
    load_default_whitelist,
    load_project_whitelist,
    save_project_whitelist,
)
from anonymizer.utils.translate import _
from anonymizer.view.blur_face_results import (
    face_blur_mode_from_menu_label,
    face_blur_mode_menu_values,
)
from anonymizer.view.ctk_safe import mark_ctk_window_alive, mark_ctk_window_destroyed
from anonymizer.view.face_blur_review_dialog import show_face_blur_review_dialog
from anonymizer.view.harmonize_results import show_harmonize_results_view
from anonymizer.view.image import ImageViewer
from anonymizer.view.navigation import find_phi_index_parent

logger = logging.getLogger(__name__)


class SeriesLoadError(Exception):
    """Raised when DICOM series pixels cannot be loaded for Series View."""


def show_series_view(
    parent: tk.Misc,
    *,
    anon_model: AnonymizerModel,
    series_path: Path,
    project_model: ProjectModel | None = None,
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
    return SeriesView(
        parent,
        anon_model=anon_model,
        series_path=series_path,
        project_model=project_model,
    )


# Edit Contexts:
class EditContext(StrEnum):
    FRAME = auto()  # apply edits to current frame only
    SERIES = auto()  # apply edits to every frame in series
    # TODO: PROJECT = auto()  # apply edits to all series in project


class SeriesView(ctk.CTkToplevel):
    BUTTON_WIDTH = 100
    PAD = 10
    LOAD_POLL_MS = 100
    PROGRESS_SLICE_THRESHOLD = 400
    DEFAULT_WIDTH = 960
    DEFAULT_HEIGHT = 640
    STATUS_WRAPLENGTH = 600
    LOADING_SHELL_WIDTH = 420
    LOADING_SHELL_HEIGHT = 72
    LOADING_SHELL_PAD = 12
    LOAD_PROGRESS_PULSE_MS = 180

    def __init__(
        self,
        parent,
        anon_model: AnonymizerModel,
        series_path: Path,
        project_model: ProjectModel | None = None,
    ):
        super().__init__(master=parent)
        mark_ctk_window_alive(self)

        self._parent = parent
        self._anon_model = anon_model
        self._project_model = project_model
        self._series_path = series_path
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
        self._series_geometry: SeriesGeometryResult | None = None
        self._face_blur_eligibility_cache: FaceBlurEligibility | None = None
        self._face_blur_eligibility_geometry: SeriesGeometryResult | None = None
        self._rebuild_after_id: str | None = None
        self._rebuild_pending = False
        self._ui_rebuilding = False
        self._destroyed = False
        self._closing = False

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

    def _widget_alive(self) -> bool:
        if getattr(self, "_destroyed", False) or getattr(self, "_closing", False):
            return False
        with contextlib.suppress(tk.TclError):
            return bool(self.winfo_exists())
        return False

    @staticmethod
    def _unregister_customtkinter_window(window: tk.Misc) -> None:
        mark_ctk_window_destroyed(window)

    def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        self._stop_rebuild_ui()
        self._stop_load_progress_pulse()
        mark_ctk_window_destroyed(self)
        super().destroy()

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
    def _load_series_data(
        series_path: Path,
    ) -> tuple[Dataset, np.ndarray, tuple[Path, ...], SeriesGeometryResult | None]:
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
        self._series_geometry = ensure_series_geometry(
            self._series_path,
            ds=self._ds,
            cached=self._series_geometry,
        )
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
        if not self._widget_alive() or not self._loading:
            return

        while True:
            try:
                kind, payload = self._load_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "done":
                ds, frames, slice_paths, series_geometry = payload
                self.after_idle(
                    lambda d=ds, f=frames, p=slice_paths, g=series_geometry: self._finish_loading(
                        ds=d,
                        frames=f,
                        slice_paths=p,
                        series_geometry=g,
                    )
                )
                return
            if kind == "error":
                self._loading = False
                logger.error("Could not open series view for %s: %s", self._series_path, payload)
                messagebox.showerror(
                    title=_("Series View"),
                    message=_("Could not load this series.") + f"\n\n{self._series_path}\n\n{payload}",
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

    def _apply_viewer_display_sizing(self, *, detach_companion: bool = False) -> None:
        """Apply V18-style viewer sizing after layout (single-pane or dual-pane)."""
        if not hasattr(self, "image_viewer") or self.image_viewer is None:
            return
        viewer = self.image_viewer
        if detach_companion:
            viewer.detach_companion_stack()
        self.update_idletasks()
        viewer._resize_to_viewport_enabled = False
        viewer._set_initial_size()
        self._fit_window_to_content()
        viewer.sync_viewport_after_layout()
        viewer._resize_to_viewport_enabled = True

    def _apply_initial_viewer_display(self) -> None:
        """Apply master-style viewer sizing once the Series View window is mapped."""
        self._apply_viewer_display_sizing(detach_companion=True)

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
        return not self._ui_rebuilding and not self._loading

    def _refresh_model_aware_toolbar_buttons(self) -> None:
        """Restore harmonize / blur / TS-cache buttons from ORM and eligibility rules."""
        self._refresh_harmonize_button()
        self._refresh_blur_face_ui()
        self._refresh_clear_ts_cache_button()

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

        if busy:
            for attr in (
                "harmonize_button",
                "blur_face_button",
                "blur_face_mode_menu",
                "clear_ts_cache_button",
            ):
                widget = getattr(self, attr, None)
                if widget is not None:
                    with contextlib.suppress(tk.TclError):
                        widget.configure(state="disabled")
        else:
            self._refresh_model_aware_toolbar_buttons()

        if hasattr(self, "save_button") and busy:
            with contextlib.suppress(tk.TclError):
                self.save_button.configure(state="disabled")

        if hasattr(self, "image_viewer"):
            with contextlib.suppress(tk.TclError):
                self.image_viewer.set_interaction_enabled(enabled)

        with contextlib.suppress(tk.TclError):
            self.configure(cursor="watch" if busy else "")

    def _flush_pending_rebuild_ui(self) -> None:
        if not self._rebuild_pending:
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
        self._stop_rebuild_ui()
        self._set_series_interaction_enabled(False)
        self._rebuild_after_id = self.after_idle(self._rebuild_ui_on_main_thread)

    def _rebuild_ui_on_main_thread(self) -> None:
        self._rebuild_after_id = None
        if not self.winfo_exists():
            return
        self._ui_rebuilding = True
        try:
            self._rebuild_ui()
        finally:
            self._ui_rebuilding = False
            self._set_series_interaction_enabled(True)

    def _destroy_ui(self) -> None:
        """Remove Series View widgets while keeping loaded series data in memory."""
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
        self._whitelist_frame = ctk.CTkFrame(self._sv_frame)
        self._whitelist_frame.grid(row=0, column=0, sticky="nsew", padx=self.PAD, pady=self.PAD)
        self._whitelist_frame.grid_columnconfigure(2, weight=1)
        self._whitelist_frame.grid_rowconfigure(3, weight=1)

        # Whitelist buttons:
        whitelist_title = ctk.CTkLabel(self._whitelist_frame, text=_("WHITE LIST"))
        whitelist_title.grid(row=0, columnspan=2, sticky="ew")
        self.whitelist_defaults_button = ctk.CTkButton(
            self._whitelist_frame, text=_("Defaults"), command=self.whitelist_defaults_button_clicked
        )
        self.whitelist_defaults_button.grid(row=1, column=0, sticky="ew", padx=self.PAD, pady=self.PAD)
        self.whitelist_clear_button = ctk.CTkButton(
            self._whitelist_frame, text=_("Clear"), command=self.clear_whitelist
        )
        self.whitelist_clear_button.grid(row=1, column=1, sticky="ew", padx=(0, self.PAD), pady=self.PAD)

        # Whitelist entry:
        self.whitelist_entry = ctk.CTkEntry(self._whitelist_frame)
        self.whitelist_entry.bind("<Return>", self.whitelist_button_clicked_or_entry_return)
        self.whitelist_entry.grid(row=2, columnspan=3, sticky="ew")

        scrollbar = ctk.CTkScrollbar(self._whitelist_frame, orientation="vertical")
        self.whitelist = tk.Listbox(
            self._whitelist_frame,
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

        # Control Frame (toolbar row, status line, save row):
        self.control_frame = ctk.CTkFrame(self._sv_frame)
        self.control_frame.grid(row=1, columnspan=2, sticky="ew", padx=self.PAD, pady=self.PAD)
        self.control_frame.grid_columnconfigure(0, weight=1)

        text_edit_group = ctk.CTkFrame(self.control_frame, fg_color="transparent")
        self._text_edit_group = text_edit_group
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
        harmonize_blur_group.grid(row=0, column=1, padx=(0, self.PAD), pady=self.PAD, sticky="e")
        harmonize_state = self._harmonize_button_state()
        self.harmonize_button = ctk.CTkButton(
            harmonize_blur_group,
            width=160,
            text=_("Harmonize Description"),
            command=self.harmonize_description_button_clicked,
            state=harmonize_state,
        )
        self.harmonize_button.grid(row=0, column=0, padx=(self.PAD, 2), pady=0, sticky="e")
        self.blur_face_button = ctk.CTkButton(
            harmonize_blur_group,
            width=120,
            text=_("Blur Face"),
            command=self.blur_face_button_clicked,
            state="disabled",
        )
        self.blur_face_button.grid(row=0, column=1, padx=2, pady=0, sticky="e")
        self.blur_face_mode_var = tk.StringVar(value=face_blur_mode_menu_values()[0])
        self.blur_face_mode_menu = ctk.CTkOptionMenu(
            harmonize_blur_group,
            width=140,
            values=face_blur_mode_menu_values(),
            variable=self.blur_face_mode_var,
        )
        self.blur_face_mode_menu.grid(row=0, column=2, padx=(2, 2), pady=0, sticky="e")
        self.clear_ts_cache_button = ctk.CTkButton(
            harmonize_blur_group,
            width=130,
            text=_("Clear TS Cache"),
            command=self.clear_ts_cache_button_clicked,
            state=self._clear_ts_cache_button_state(),
        )
        self.clear_ts_cache_button.grid(row=0, column=3, padx=(2, self.PAD), pady=0, sticky="e")
        self._apply_ai_feature_visibility()

        self._status_label = ctk.CTkLabel(
            self.control_frame,
            text="",
            anchor="w",
            justify="left",
            wraplength=self.STATUS_WRAPLENGTH,
        )
        self._status_label.grid(
            row=1,
            column=0,
            columnspan=2,
            padx=self.PAD,
            pady=(0, self.PAD),
            sticky="w",
        )

        self._series_status_label = ctk.CTkLabel(
            self.control_frame,
            text="",
            anchor="w",
            justify="left",
        )
        self._series_status_label.grid(
            row=2,
            column=0,
            padx=self.PAD,
            pady=(0, self.PAD),
            sticky="w",
        )

        self.save_button = ctk.CTkButton(
            self.control_frame,
            width=130,
            text=_("Save Pixel Changes"),
            command=self.save_series_button_clicked,
        )
        self.save_button.grid(row=2, column=1, padx=self.PAD, pady=(0, self.PAD), sticky="e")
        self.save_button.configure(state="disabled")
        self._show_default_context_line()
        self._refresh_series_processing_status()

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

    def _anon_series_uid(self) -> str | None:
        if self._ds is None:
            return None
        return str(self._ds.SeriesInstanceUID)

    def _refresh_series_processing_status(self) -> None:
        if not hasattr(self, "_series_status_label"):
            return
        anon_uid = self._anon_series_uid()
        if anon_uid is None:
            self._series_status_label.configure(text="")
            return
        status = self._anon_model.get_series_processing_status(anon_uid)
        if status is None:
            self._series_status_label.configure(text="")
            return
        already_applied = self._anon_model.series_has_face_blur(anon_uid)
        include_face_blur = face_blur_status_applicable(
            self._face_blur_eligibility(),
            already_applied=already_applied,
        )
        self._series_status_label.configure(
            text=format_series_processing_status(status, include_face_blur=include_face_blur),
        )

    def _harmonize_button_visible(self) -> bool:
        if get_ai_session().enable_harmonize:
            return True
        return getattr(self._ds, "Modality", None) == "CT" and tseg_cache_summary(self._series_path).exists

    def _clear_ts_cache_button_visible(self) -> bool:
        session = get_ai_session()
        if session.enable_harmonize or session.enable_face_blur:
            return True
        return getattr(self._ds, "Modality", None) == "CT" and tseg_cache_summary(self._series_path).exists

    def _apply_ai_feature_visibility(self) -> None:
        session = get_ai_session()
        face_on = session.enable_face_blur
        if hasattr(self, "harmonize_button"):
            if self._harmonize_button_visible():
                self.harmonize_button.grid()
                self._refresh_harmonize_button()
            else:
                self.harmonize_button.grid_remove()
        if hasattr(self, "blur_face_button"):
            if face_on:
                self.blur_face_button.grid()
                if hasattr(self, "blur_face_mode_menu"):
                    self.blur_face_mode_menu.grid()
                self._refresh_blur_face_ui()
            else:
                self.blur_face_button.grid_remove()
                if hasattr(self, "blur_face_mode_menu"):
                    self.blur_face_mode_menu.grid_remove()
        if hasattr(self, "clear_ts_cache_button"):
            if self._clear_ts_cache_button_visible():
                self.clear_ts_cache_button.grid()
                self._refresh_clear_ts_cache_button()
            else:
                self.clear_ts_cache_button.grid_remove()

    def update_status(self, message: str) -> None:
        """Overwrite the context line with transient operation status."""
        logger.info("Series view: %s", message)
        if hasattr(self, "_status_label"):
            self._status_label.configure(text=message)

    def _harmonize_button_state(self) -> str:
        if not get_ai_session().enable_harmonize:
            return "disabled"
        if not harmonize_allowed():
            return "disabled"
        if getattr(self._ds, "Modality", None) != "CT":
            return "disabled"
        anon_uid = self._anon_series_uid()
        if anon_uid is not None and self._anon_model.series_is_harmonized(anon_uid):
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
        self._refresh_model_aware_toolbar_buttons()
        self._show_default_context_line()
        self._refresh_series_processing_status()

    def _on_series_description_updated(self) -> None:
        self._update_title()
        self._series_geometry = None
        self._face_blur_eligibility_cache = None
        self._face_blur_eligibility_geometry = None
        self._refresh_analysis_cache_ui()
        self._refresh_series_processing_status()

    def _face_blur_eligibility(self) -> FaceBlurEligibility:
        geometry = self._ensure_series_geometry()
        if self._face_blur_eligibility_cache is not None and geometry is self._face_blur_eligibility_geometry:
            return self._face_blur_eligibility_cache

        eligibility = evaluate_face_blur_eligibility(
            self._series_path,
            ds=self._ds,
            geometry=geometry,
            enable_tseg_face=get_ai_session().enable_face_blur,
            face_blur_already_applied=(
                self._anon_model.series_has_face_blur(str(self._ds.SeriesInstanceUID))
                if self._ds is not None
                else False
            ),
        )
        self._face_blur_eligibility_cache = eligibility
        self._face_blur_eligibility_geometry = geometry
        return eligibility

    def _blur_face_toolbar_state(self) -> str:
        if not get_ai_session().enable_face_blur:
            return "disabled"
        if not face_blur_allowed():
            return "disabled"
        anon_uid = self._anon_series_uid()
        if anon_uid is not None and self._anon_model.series_has_face_blur(anon_uid):
            return "disabled"
        eligibility = self._face_blur_eligibility()
        if eligibility.decision == FaceBlurGateDecision.BLOCK:
            return "disabled"
        return "normal"

    def _refresh_blur_face_ui(self) -> None:
        state = self._blur_face_toolbar_state()
        if hasattr(self, "blur_face_button"):
            self.blur_face_button.configure(state=state)
        if hasattr(self, "blur_face_mode_menu"):
            self.blur_face_mode_menu.configure(state=state)

    def _selected_face_blur_mode(self) -> FaceBlurMode:
        if not hasattr(self, "blur_face_mode_var"):
            return FaceBlurMode.GAUSSIAN
        return face_blur_mode_from_menu_label(self.blur_face_mode_var.get())

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

    def process_single_frame_ocr(self, frame_index: int):
        """Performs OCR on a single frame, filters, and stores results."""
        results = OcrService.instance().detect_text(
            pixels=apply_windowing(
                self.image_viewer.current_wl,
                self.image_viewer.current_ww,
                self.image_viewer.images[frame_index],
            ),
            draw_boxes=False,
        )
        if results:
            logger.debug(f"OCR Results:\n{pformat(results)}")
            self.detected_text[frame_index] = results
            self.draw_text_overlay(frame_index)

    def filter_text_data(self, frame_index: int, similarity_threshold: float = 0.75) -> list[OCRText]:
        """Apply user whitelist filtering via shared OCR filter helpers."""
        if frame_index not in self.detected_text:
            return []

        detections = self.detected_text[frame_index]
        whitelist_set = self.get_whitelist_set()
        if not whitelist_set:
            return detections

        return filter_ocr_detections(
            detections,
            whitelist=list(whitelist_set),
            whitelist_similarity=similarity_threshold,
        )

    def draw_text_overlay(self, frame_index: int):
        """Draws text boxes on the overlay for the given frame, based on filtered text_data."""
        filtered_text_data = self.filter_text_data(frame_index)  # Filter *before* drawing
        self.image_viewer.set_text_overlay_data(frame_index, filtered_text_data)

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

        if self.edit_context == EditContext.FRAME:
            self.update_status(_("Detecting text in current image") + "…")
            self.process_single_frame_ocr(self.image_viewer.current_image_index)
            self.update_status(_("Text detection complete"))
        else:
            self.detect_text_for_series()
            self.update_status(_("Text detection complete"))

        # TODO: work out what to do beyond propagting edits in overlays when edit context is PROJECT

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
        if not get_ai_session().enable_harmonize:
            messagebox.showinfo(
                title=_("Harmonize"),
                message=_("Harmonize is not enabled. Open AI Features Setup from the Welcome screen or Help menu."),
                parent=self,
            )
            return
        if not harmonize_allowed():
            messagebox.showinfo(
                title=_("Harmonize"),
                message=_("Harmonize is not ready yet. Open AI Features Setup to download models."),
                parent=self,
            )
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
        self._series_geometry = None
        self._face_blur_eligibility_cache = None
        self._face_blur_eligibility_geometry = None
        self._refresh_analysis_cache_ui()
        self._refresh_series_processing_status()

    def clear_ts_cache_button_clicked(self) -> None:
        if self._ds is None or getattr(self._ds, "Modality", None) != "CT":
            return

        summary = tseg_cache_summary(self._series_path)
        if not summary.exists:
            return

        size_mb = summary.size_bytes / (1024 * 1024)
        size_text = f"{size_mb:.1f} MB" if size_mb >= 0.1 else _("< 0.1 MB")

        cache_message = (
            _("Delete analysis cache for this series?")
            + "\n\n"
            + _("Removes geometry, segmentation masks, contrast analysis, and face mask under")
            + f" {TSEG_CACHE_DIRNAME}/ ({size_text}, {summary.file_count} "
            + _("files")
            + ").\n\n"
            + _("DICOM images and series description are not changed.")
            + "\n\n"
            + _("Harmonize analysis can be re-run after clearing the cache.")
        )
        anon_uid = self._anon_series_uid()
        if anon_uid is not None and self._anon_model.series_has_face_blur(anon_uid):
            cache_message += "\n\n" + _(
                "Face blur has already been applied; blurred pixels and Blur Face status are unchanged."
            )

        confirmed = messagebox.askyesno(
            title=_("Clear Analysis Cache"),
            message=cache_message,
            parent=self,
            default="no",
        )
        if not confirmed:
            return

        logger.info("Clearing TS cache for %s", self._series_path)
        clear_series_tseg_cache(
            self._series_path,
            anon_model=self._anon_model,
            anon_series_uid=anon_uid,
        )
        self._series_geometry = None
        self._face_blur_eligibility_cache = None
        self._face_blur_eligibility_geometry = None
        self.after_idle(self._finish_clear_ts_cache)

    def _finish_clear_ts_cache(self) -> None:
        if not self._widget_alive():
            return
        self._refresh_analysis_cache_ui()
        self._apply_ai_feature_visibility()
        self.update_status(_("Analysis cache cleared"))
        self._refresh_series_processing_status()

    def blur_face_button_clicked(self) -> None:
        anon_uid = self._anon_series_uid()
        if anon_uid is not None and self._anon_model.series_has_face_blur(anon_uid):
            messagebox.showinfo(
                title=_("Blur Face"),
                message=face_blur_gate_message(FaceBlurGateReason.ALREADY_APPLIED),
                parent=self,
            )
            return
        if not self._series_interaction_allowed() or self._blur_face_toolbar_state() != "normal":
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

        blur_mode = self._selected_face_blur_mode()
        index_parent = find_phi_index_parent(self) or self._parent

        logger.info(
            "Series View: opening face blur review for %s (gate=%s)",
            self._series_path,
            eligibility.reason.name,
        )
        self._on_cancel()
        show_face_blur_review_dialog(
            index_parent,
            anon_model=self._anon_model,
            series_path=self._series_path,
            blur_mode=blur_mode,
        )

    def save_series_button_clicked(self):
        if self._frames is None or self._ds is None:
            logger.error("CRITICAL: No frames or dataset to save")
            return

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
            if hasattr(self, "image_viewer"):
                texts_by_frame = collect_series_view_pixel_phi_texts(self.image_viewer)
                if texts_by_frame:
                    projection_count = 0 if self.single_frame else 3
                    apply_series_view_pixel_phi(
                        self._anon_model,
                        self._slice_paths,
                        texts_by_frame,
                        projection_frame_count=projection_count,
                        anon_series_uid=str(self._ds.SeriesInstanceUID),
                    )
            self.save_button.configure(state="disabled")
            self._refresh_series_processing_status()
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
        if self._frames is None:
            return
        logger.info(
            "SeriesView releasing %.1f MB of in-memory frame data (_frames=%.1fMB)",
            self._frames.nbytes / (1024 * 1024),
            self._frames.nbytes / (1024 * 1024),
        )

    @staticmethod
    def _schedule_post_close_gc(parent: tk.Misc, rss_before: float | None) -> None:
        """Run GC on the next idle tick so Tk finishes teardown first (avoids Tk 9 bus errors)."""

        def _run() -> None:
            gc.collect()
            gc.collect()
            if rss_before is None:
                return
            rss_after = log_process_memory("series_view_close_after")
            if rss_after is not None:
                logger.info(
                    "SeriesView close memory delta: %.1f MB (before %.1f MB, after %.1f MB)",
                    rss_before - rss_after,
                    rss_before,
                    rss_after,
                )

        with contextlib.suppress(tk.TclError):
            parent.after_idle(_run)

    def _release_image_viewer(
        self,
        viewer: ImageViewer | None,
        *,
        destroy_widget: bool = False,
    ) -> None:
        if viewer is None:
            return
        try:
            viewer.release_resources()
            if destroy_widget:
                viewer.destroy()
        except tk.TclError:
            logger.debug("ImageViewer already destroyed during SeriesView close")
            return

    def _release_all_viewer_resources(self) -> None:
        if hasattr(self, "image_viewer"):
            self._release_image_viewer(self.image_viewer)

    def _release_series_data(self) -> None:
        self._frames = None
        self._slice_paths = ()
        self._ds = None
        self._series_geometry = None
        self.detected_text.clear()

    def _on_cancel(self):
        logger.info("_on_cancel")
        if getattr(self, "_closing", False):
            return
        self._closing = True
        mark_ctk_window_destroyed(self)
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

        self._release_all_viewer_resources()
        self._release_series_data()

        with contextlib.suppress(tk.TclError):
            self.grab_release()

        parent = self._parent
        self.destroy()
        self._schedule_post_close_gc(parent, rss_before)
