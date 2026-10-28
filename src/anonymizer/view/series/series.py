import contextlib
import logging
import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from pprint import pformat
from tkinter import filedialog, messagebox

import customtkinter as ctk
import numpy as np
from pydicom import Dataset, dcmread

from anonymizer.controller.project import ProjectController
from anonymizer.controller.series.series_io import (
    LoadedSeries,
    SeriesProjections,
    compute_series_projections,
)
from anonymizer.controller.series.series_overlay import LayerType, OCRText, OverlayData, Segmentation, UserRectangle
from anonymizer.controller.series.workspace import (
    TSEG_CACHE_DIRNAME,
    Algorithm,
    AnnotateSession,
    FaceBlurEligibility,
    FaceBlurGateDecision,
    FaceBlurGateReason,
    FaceBlurMode,
    ImportProfile,
    OcrEditContext,
    OcrRemoveMode,
    OcrWhitelistMatchMode,
    OcrWhitelistMatchSettings,
    PixelPhiRemovalMode,
    SeriesGeometryResult,
    SeriesLoadError,
    SeriesViewSaveRequest,
    SeriesWorkspace,
    WorkState,
    blur_face_toolbar_visible,
    clear_cache_button_visible,
    collect_series_view_embedded_phi_texts,
    commit_user_rects_to_exclude,
    default_whitelist_match_settings,
    describe_match_settings,
    edit_context_display_label,
    edit_context_menu_values,
    edit_context_toolbar_visible,
    exclude_rects_fingerprint,
    face_blur_allowed,
    face_blur_gate_message,
    face_blur_status_applicable,
    filter_series_view_ocr_overlay,
    format_ocr_detection_complete_status,
    format_series_view_geometry_line,
    harmonize_allowed_for_modality,
    load_default_whitelist,
    load_modality_whitelist,
    load_modality_whitelist_match_settings,
    load_project_exclude_rects,
    match_mode_description,
    match_mode_menu_label,
    match_mode_menu_labels,
    modality_exclude_rects_for_series,
    normalize_edit_context,
    normalize_ocr_remove_mode,
    normalize_pixel_phi_removal_mode,
    normalize_user_rects,
    ocr_detect_tooltip,
    ocr_image_for_frame,
    ocr_remove_enabled,
    ocr_remove_mode_display_label,
    ocr_remove_mode_menu_labels,
    ocr_remove_mode_tooltip,
    ocr_results_available_for_edit_context,
    pixel_phi_removal_mode_menu_labels,
    pixel_phi_removal_mode_option_label,
    read_cached_segmentation_mode,
    read_primary_segment_voxels,
    save_modality_whitelist_match_settings,
    save_project_whitelist,
    stackable_dicom_paths,
)
from anonymizer.utils.dicom import get_wl_ww
from anonymizer.utils.memory import collect_garbage_safe, log_process_memory
from anonymizer.utils.modalities import Modality
from anonymizer.utils.storage.dicom_tree import get_dcm_files
from anonymizer.utils.translate import _
from anonymizer.utils.windowing import apply_windowing
from anonymizer.view.ai.blur_face_results import face_blur_mode_from_menu_label, face_blur_mode_menu_values
from anonymizer.view.ai.face_blur_review_dialog import show_face_blur_review_dialog
from anonymizer.view.ai.harmonize_description import (
    harmonize_button_visible,
    harmonize_description_button_label,
    launch_harmonize_description,
)
from anonymizer.view.ai.harmonize_results import HarmonizeBatchOutcome
from anonymizer.view.common.app_window import AppCTkToplevel, refresh_app_window_menu
from anonymizer.view.common.ctk_safe import mark_ctk_window_destroyed
from anonymizer.view.common.fonts import AppFonts
from anonymizer.view.common.job_poller import start_background_job
from anonymizer.view.common.navigation import find_dataset_view_parent, return_to_dataset_view
from anonymizer.view.common.tooltip import bind_hover_tooltip
from anonymizer.view.common.ux_fields import (
    button_width_for_label,
    option_menu_width_for_labels,
    truncate_series_description,
)
from anonymizer.view.series.anatomy_overlay import (
    collect_primary_segment_voxels,
    color_bgr_for_structure,
    contour_mask_slice,
    load_primary_segment_mask,
    mask_slice_to_segmentations,
    merge_structure_overlays,
    order_structures_by_voxels,
    shift_overlays_to_viewer_frames,
    structure_button_label,
)
from anonymizer.view.series.image import ImageViewer
from anonymizer.view.series.metadata_assessment_dialog import MetadataAssessmentDialog
from anonymizer.view.series.new_segment_dialog import show_new_segment_dialog

logger = logging.getLogger(__name__)


def show_series_view(
    parent: tk.Misc,
    *,
    controller: ProjectController,
    series_path: Path,
    fonts: AppFonts | None = None,
    preloaded: LoadedSeries | None = None,
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
        controller=controller,
        series_path=series_path,
        fonts=fonts,
        preloaded=preloaded,
    )


@dataclass(frozen=True)
class SeriesViewStartupSpec:
    """Precomputed startup layout from native frame size, screen budget, and chrome."""

    native_size: tuple[int, int]
    display_size: tuple[int, int]
    window_size: tuple[int, int]
    canvas_budget: tuple[int, int]
    segmentation_reserved: bool = False


class SeriesView(AppCTkToplevel):
    BUTTON_WIDTH = 100
    PAD = 10
    LOAD_POLL_MS = 100
    PROGRESS_SLICE_THRESHOLD = 400
    DEFAULT_WIDTH = 960
    DEFAULT_HEIGHT = 640
    MIN_IMAGE_VIEWPORT = 128
    STATUS_WRAPLENGTH = 600
    LOADING_SHELL_WIDTH = 420
    LOADING_SHELL_HEIGHT = 72
    LOADING_SHELL_PAD = 12
    LOAD_PROGRESS_PULSE_MS = 180

    def __init__(
        self,
        parent,
        controller: ProjectController,
        series_path: Path,
        fonts: AppFonts | None = None,
        *,
        preloaded: LoadedSeries | None = None,
    ):
        super().__init__(master=parent)
        self._fonts = fonts

        self._parent = parent
        self._controller = controller
        self._series_path = series_path
        self._workspace = SeriesWorkspace(controller, series_path)
        self.edit_context: OcrEditContext = OcrEditContext.FRAME
        self.ocr_remove_mode: OcrRemoveMode = OcrRemoveMode.NON_WHITELISTED
        self.detected_text: dict[int, list[OCRText]] = {}  # Store all detected text per frame
        # Texts removed from pixels (overlay is cleared on Remove Text before Save).
        self._removed_pixel_phi_by_frame: dict[int, list[str]] = {}
        self._pixel_phi_dirty = False
        # Fingerprint of last saved/loaded modality exclude rects (normalized).
        self._saved_exclude_fingerprint: tuple[tuple[float, float, float, float], ...] = ()
        # Raw OCR lines per frame; cleansed + promoted to Basic Text SR on Save for pixel text reports.
        self._ocr_transcript_by_frame: dict[int, list[str]] = {}
        self._whitelist_changed = False
        self._whitelist_match_changed = False
        self._whitelist_match_settings = default_whitelist_match_settings()
        self._loading = True
        self._load_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._loading_shell: ctk.CTkFrame | None = None
        self._load_progress: ctk.CTkProgressBar | None = None
        self._load_progress_after_id: str | None = None
        self._load_progress_value = 0.0
        try:
            self._cached_dcm_paths = stackable_dicom_paths(series_path)
        except ValueError:
            self._cached_dcm_paths = None
        self._show_load_progress = len(self._cached_dcm_paths or []) > self.PROGRESS_SLICE_THRESHOLD

        self._ds: Dataset | None = None
        self._frames: np.ndarray | None = None
        self._projections: SeriesProjections | None = None
        self._loaded: LoadedSeries | None = None
        self._slice_paths: tuple[Path, ...] = ()
        self.single_frame = False
        self._dicom_wl: float | None = None
        self._dicom_ww: float | None = None
        self._series_geometry: SeriesGeometryResult | None = None
        self._face_blur_eligibility_cache: FaceBlurEligibility | None = None
        self._face_blur_eligibility_geometry: SeriesGeometryResult | None = None
        self._ocr_work_state = WorkState()
        self._ocr_poll_frame_index = -1
        self._ocr_detecting = False
        self._rebuild_after_id: str | None = None
        self._min_window_size: tuple[int, int] | None = None
        self._rebuild_pending = False
        self._structure_overlay_by_name: dict[str, dict[int, list[Segmentation]]] = {}
        self._structure_mask_by_name: dict[str, np.ndarray] = {}
        self._structure_contour_cancel: dict[str, threading.Event] = {}
        self._structure_contour_generation = 0
        self._structure_contour_queue: queue.Queue[
            tuple[str, dict[int, list[Segmentation]] | None, int, threading.Event]
        ] = queue.Queue()
        self._structure_contour_poll_after_id: str | None = None
        self._harmonize_view = None
        self._annotate_session: AnnotateSession | None = None
        self._annotate_save_after_id: str | None = None
        self._annotate_recontour_after_id: str | None = None
        self._pending_annotate_recontour: tuple[str, int] | None = None
        self._stroke_before: np.ndarray | None = None
        self._stroke_kind: str | None = None
        self._stroke_structure: str | None = None
        self._stroke_slice: int | None = None
        self._user_label_overlays: dict[str, dict[int, list[Segmentation]]] = {}

        self._ui_rebuilding = False
        self._startup_layout = False
        self._startup_segmentation_reserved = False
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

        if preloaded is not None:
            projections = compute_series_projections(preloaded.frames) if not preloaded.is_single_frame else None
            self._trace_load(
                "preloaded",
                slices=preloaded.frames.shape[0],
                frame=f"{preloaded.frames.shape[2]}x{preloaded.frames.shape[1]}",
            )
            self.after_idle(
                lambda: self._finish_loading(
                    loaded=preloaded,
                    frames=preloaded.frames,
                    projections=projections,
                    series_geometry=None,
                )
            )
            return

        self._trace_load(
            "async_start",
            slices=len(self._cached_dcm_paths or ()),
            progress_shell=self._show_load_progress,
        )
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

    def _ensure_series_geometry(self) -> SeriesGeometryResult | None:
        self._series_geometry = self._workspace.ensure_geometry(ds=self._ds)
        return self._series_geometry

    def _load_worker(self) -> None:
        self._log_series_memory("load_worker_start")
        try:
            workspace_load = self._workspace.load_series_workspace(
                dcm_paths=self._cached_dcm_paths,
            )
            payload = (
                workspace_load.loaded,
                workspace_load.frames,
                workspace_load.projections,
                workspace_load.series_geometry,
            )
            self._log_series_memory("load_worker_done", array=workspace_load.frames)
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
                loaded, frames, projections, series_geometry = payload
                self._trace_load(
                    "worker_done",
                    slices=frames.shape[0],
                    frame=f"{frames.shape[2]}x{frames.shape[1]}",
                    projections=projections is not None,
                )
                self.after_idle(
                    lambda loaded=loaded, frames=frames, projections=projections, g=series_geometry: (
                        self._finish_loading(
                            loaded=loaded,
                            frames=frames,
                            projections=projections,
                            series_geometry=g,
                        )
                    )
                )
                return
            if kind == "error":
                self._trace_load("worker_error", error=str(payload))
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
        loaded: LoadedSeries,
        frames: np.ndarray,
        projections: SeriesProjections | None,
        series_geometry: SeriesGeometryResult | None,
    ) -> None:
        self._log_series_memory("finish_loading_start", array=frames)
        self._trace_load(
            "finish_loading",
            slices=frames.shape[0],
            frame=f"{frames.shape[2]}x{frames.shape[1]}",
            projections=projections is not None,
        )
        self._loading = False
        self._loaded = loaded
        self._ds = loaded.metadata
        self._frames = frames
        self._projections = projections
        self._slice_paths = loaded.slice_paths
        self._series_geometry = series_geometry
        self._workspace.set_geometry_cache(series_geometry)
        self.single_frame = loaded.is_single_frame
        self._dicom_wl, self._dicom_ww = loaded.default_window

        self._stop_load_progress_pulse()
        if self._loading_shell is not None:
            self.withdraw()
            self._loading_shell.destroy()
            self._loading_shell = None
            self._load_progress = None
            self.update_idletasks()

        self.resizable(True, True)
        self._clear_window_maxsize_cap()
        self._build_ui()
        self._log_series_memory("after_build_ui", array=self._frames)
        self._trace_load("build_ui_done")
        self._update_title()
        self._present_series_view()

    def _remember_dicom_wl_ww(self, ds: Dataset | None = None) -> tuple[float, float]:
        """Read and cache WL/WW from DICOM headers (not viewer-adjusted values)."""
        source: Dataset | None = ds if ds is not None else self._ds
        if source is None and self._slice_paths:
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

    def _apply_fast_startup_chrome(self) -> None:
        """Toolbar and status chrome that does not read segmentation masks."""
        self._apply_ai_feature_visibility()
        self._refresh_ocr_toolbar_buttons()
        self._show_default_context_line()
        self._refresh_series_processing_status()

    def _maximum_window_size(self) -> tuple[int, int]:
        """Screen-bounded maximum; window may grow freely up to this limit."""
        return (
            int(self.winfo_screenwidth() * ImageViewer.MAX_SCREEN_PERCENTAGE),
            int(self.winfo_screenheight() * ImageViewer.MAX_SCREEN_PERCENTAGE),
        )

    def _clamp_to_screen(self, size: tuple[int, int]) -> tuple[int, int]:
        max_w, max_h = self._maximum_window_size()
        return min(size[0], max_w), min(size[1], max_h)

    def _clear_window_maxsize_cap(self) -> None:
        """CustomTkinter requires numeric maxsize; uncapped toplevels leave _max_width None and break geometry()."""
        max_w, max_h = self._maximum_window_size()
        with contextlib.suppress(tk.TclError):
            self.maxsize(max_w, max_h)

    def _window_size_for_canvas(self, canvas_size: tuple[int, int]) -> tuple[int, int]:
        """Window size required when the image canvas is exactly ``canvas_size``.

        Tk sums the real chrome (whitelist, RHS controls, toolbar, padding), which is the
        only measurement that stays correct as fonts, translations, toolbar buttons and
        segmentation controls change. Startup and chrome changes only: never called from
        the resize path, because it briefly reconfigures the canvas to take the reading.
        """
        viewer = getattr(self, "image_viewer", None)
        if viewer is None:
            return self._clamp_to_screen((self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT))
        restore = viewer.current_size
        try:
            viewer.canvas.config(width=canvas_size[0], height=canvas_size[1])
            self.update_idletasks()
            required = (self.winfo_reqwidth(), self.winfo_reqheight())
            viewer.canvas.config(width=restore[0], height=restore[1])
            self.update_idletasks()
        except tk.TclError:
            return self._clamp_to_screen((self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT))
        return self._clamp_to_screen(required)

    def _minimum_window_size(self) -> tuple[int, int]:
        """Smallest window that keeps whitelist, image, histogram, and player visible."""
        return self._window_size_for_canvas((self.MIN_IMAGE_VIEWPORT, self.MIN_IMAGE_VIEWPORT))

    def _native_window_dimensions(self) -> tuple[int, int]:
        """Window size that shows the native image at 1:1 alongside the real chrome."""
        if self._frames is None:
            return self._clamp_to_screen((self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT))
        return self._window_size_for_canvas((int(self._frames.shape[2]), int(self._frames.shape[1])))

    def _refresh_minimum_window_size(self) -> tuple[int, int]:
        """Re-probe and apply minsize after chrome changes; cache for the resize clamp."""
        min_size = self._minimum_window_size()
        self._min_window_size = min_size
        with contextlib.suppress(tk.TclError):
            self.minsize(*min_size)
        return min_size

    def _size_window_for_native_image(self) -> None:
        """While withdrawn, size the window so the image column can reach native resolution."""
        if self._frames is None:
            self._fit_window_to_content()
            return
        width, height = self._native_window_dimensions()
        min_w, min_h = self._refresh_minimum_window_size()
        width, height = max(width, min_w), max(height, min_h)
        pos_x, pos_y = self.winfo_x(), self.winfo_y()
        if pos_x <= 0 and pos_y <= 0:
            self._position_near_parent(width=width, height=height)
        else:
            self.geometry(f"{width}x{height}+{max(0, pos_x)}+{max(0, pos_y)}")

    def _size_window_for_startup_paint(self, window_size: tuple[int, int]) -> None:
        """Apply a predetermined window size before the first visible image paint."""
        self._apply_startup_geometry(window_size)

    def _apply_startup_geometry(self, window_size: tuple[int, int]) -> None:
        pos_x, pos_y = self.winfo_x(), self.winfo_y()
        if pos_x <= 0 and pos_y <= 0:
            self._position_near_parent(width=window_size[0], height=window_size[1])
        else:
            self.geometry(f"{window_size[0]}x{window_size[1]}+{max(0, pos_x)}+{max(0, pos_y)}")

    @staticmethod
    def _format_trace_size(size: tuple[int, int]) -> str:
        return f"{size[0]}x{size[1]}"

    def _startup_canvas_budget(self) -> tuple[int, int]:
        """Drawable image area inside the current window geometry (startup only; not viewport_size)."""
        viewer = self.image_viewer
        self.update_idletasks()
        frame_w = viewer.image_frame.winfo_width()
        frame_h = viewer.image_frame.winfo_height()
        if frame_w <= 1 or frame_h <= 1:
            frame_w = viewer.image_frame.winfo_reqwidth()
            frame_h = viewer.image_frame.winfo_reqheight()
        return viewer._viewport_from_frame_event(max(frame_w, 1), max(frame_h, 1))

    def _compute_startup_window_size(self) -> tuple[int, int]:
        """Window outer size from native frame, chrome, and screen estate (no viewport probe)."""
        if self._frames is None:
            return self._clamp_to_screen((self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT))
        viewer = getattr(self, "image_viewer", None)
        native_window = self._native_window_dimensions()
        max_w, max_h = self._maximum_window_size()
        min_w, min_h = self._refresh_minimum_window_size()
        if native_window[0] <= max_w and native_window[1] <= max_h:
            return max(native_window[0], min_w), max(native_window[1], min_h)
        if viewer is None:
            return self._clamp_to_screen((max_w, max_h))
        screen_canvas = viewer._screen_canvas_budget()
        return self._window_size_for_canvas(screen_canvas)

    def _build_startup_spec(self) -> SeriesViewStartupSpec | None:
        """Predetermined startup sizes after chrome is fixed and window geometry is applied."""
        if self._frames is None:
            return None
        viewer = getattr(self, "image_viewer", None)
        if viewer is None:
            return None
        native_w, native_h = int(self._frames.shape[2]), int(self._frames.shape[1])
        native_size = (native_w, native_h)
        window_size = self._compute_startup_window_size()
        canvas_budget = self._startup_canvas_budget()
        display_size = viewer._resolve_display_size(
            canvas_budget[0],
            canvas_budget[1],
            allow_upscale=True,
        )
        if display_size is None:
            display_size = native_size
        return SeriesViewStartupSpec(
            native_size=native_size,
            display_size=display_size,
            window_size=window_size,
            canvas_budget=canvas_budget,
            segmentation_reserved=self._startup_segmentation_reserved,
        )

    def _present_series_view(self) -> None:
        """Linear startup while withdrawn: size → paint → seg chrome → show → done."""
        if not self._widget_alive():
            return
        self._startup_layout = True
        self._apply_fast_startup_chrome()
        viewer = getattr(self, "image_viewer", None)

        self._clear_window_maxsize_cap()
        reserve_segmentation = self._seg_dir_likely_has_structures()
        self._startup_segmentation_reserved = reserve_segmentation
        if viewer is not None:
            viewer.apply_fixed_chrome(
                refresh_histogram=True,
                reserve_segmentation_chrome=reserve_segmentation,
            )
        self.update_idletasks()
        window_size = self._compute_startup_window_size()
        self._size_window_for_startup_paint(window_size)
        self.update_idletasks()
        spec = self._build_startup_spec()
        if spec is None:
            self._load_segmentation_chrome()
            self.deiconify()
            self._trace_load("startup_complete", display="no_frames", viewable=1)
            if viewer is not None:
                viewer.mark_startup_complete()
            self._startup_layout = False
            self.lift()
            self.focus_force()
            self._focus_image_viewer_for_keys()
            return

        native_text = self._format_trace_size(spec.native_size)
        display_text = self._format_trace_size(spec.display_size)
        window_text = self._format_trace_size(spec.window_size)
        canvas_text = self._format_trace_size(spec.canvas_budget)
        self._trace_load(
            "startup_spec",
            native=native_text,
            display=display_text,
            window=window_text,
            canvas=canvas_text,
            seg_reserved=int(spec.segmentation_reserved),
            viewable=0,
        )
        self._trace_load("geometry_applied", window=window_text, viewable=0)
        if viewer is not None:
            self._trace_load("startup_paint", display=display_text, viewable=0)
            viewer.set_display_size(spec.display_size, refresh_histogram=True)
            self._trace_load("startup_painted", display=display_text, viewable=0, frame_index=0)
        self._load_segmentation_chrome()
        self._trace_load("seg_chrome", viewable=0)
        self.deiconify()
        self.update_idletasks()
        self._trace_load("deiconify", viewable=1)
        if viewer is not None:
            self._trace_load(
                "startup_complete",
                display=display_text,
                native_match=viewer.view_matches_actual(),
                viewable=1,
            )
        else:
            self._trace_load("startup_complete", display="no_image_viewer", viewable=1)
        self._log_series_memory("after_viewer_initial_display", array=self._frames)
        if viewer is not None:
            viewer.mark_startup_complete()
        self._startup_layout = False
        self.lift()
        self.focus_force()
        self._focus_image_viewer_for_keys()

    def _load_segmentation_chrome(self) -> None:
        """Populate segmentation panel controls before the window is shown."""
        self._refresh_segmentation_controls(defer_render=True)
        viewer = getattr(self, "image_viewer", None)
        if viewer is not None:
            viewer.apply_fixed_chrome()
            self._refresh_minimum_window_size()
            if bool(viewer._segmentation_button_meta) and not self._startup_segmentation_reserved:
                viewer.fit_to_viewport(force=True)

    def _fit_window_to_content(self) -> None:
        """Expand the window to fit the built UI (V18 auto-size after synchronous build)."""
        self.update_idletasks()
        req_w = max(self.winfo_reqwidth(), self.DEFAULT_WIDTH)
        req_h = max(self.winfo_reqheight(), self.DEFAULT_HEIGHT)
        max_w = int(self.winfo_screenwidth() * ImageViewer.MAX_SCREEN_PERCENTAGE)
        max_h = int(self.winfo_screenheight() * ImageViewer.MAX_SCREEN_PERCENTAGE)
        width = min(req_w, max_w)
        height = min(req_h, max_h)
        self._refresh_minimum_window_size()

        pos_x, pos_y = self.winfo_x(), self.winfo_y()
        if pos_x <= 0 and pos_y <= 0:
            self._position_near_parent(width=width, height=height)
        else:
            self.geometry(f"{width}x{height}+{max(0, pos_x)}+{max(0, pos_y)}")

    def _adapt_window_to_toolbar(self) -> None:
        """Grow minsize/geometry when toolbar buttons appear so ImageViewer layout stays correct."""
        if not self._widget_alive() or self._loading:
            return
        self.update_idletasks()
        max_w = int(self.winfo_screenwidth() * ImageViewer.MAX_SCREEN_PERCENTAGE)
        max_h = int(self.winfo_screenheight() * ImageViewer.MAX_SCREEN_PERCENTAGE)
        req_w = min(max(self.winfo_reqwidth(), self.DEFAULT_WIDTH), max_w)
        req_h = min(max(self.winfo_reqheight(), self.DEFAULT_HEIGHT), max_h)
        cur_w = max(self.winfo_width(), 1)
        cur_h = max(self.winfo_height(), 1)
        self._refresh_minimum_window_size()
        if cur_w < req_w or cur_h < req_h:
            self.geometry(f"{max(cur_w, req_w)}x{max(cur_h, req_h)}")
        viewer = getattr(self, "image_viewer", None)
        if viewer is not None and viewer._startup_complete:
            viewer.fit_to_viewport(force=True)

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
        if self._startup_layout:
            return
        viewer = getattr(self, "image_viewer", None)
        if viewer is not None and viewer._startup_complete:
            viewer._request_viewport_fit()

    def _capture_whitelist_items(self) -> list[str]:
        if not hasattr(self, "whitelist"):
            return []
        return [str(item) for item in self.whitelist.get(0, tk.END)]

    def _log_whitelist_trace(self, action: str, *, delta: str | None = None) -> None:
        modality = self._ds.Modality if self._ds is not None else None
        project_dir = self._controller.model.storage_dir
        items = self._capture_whitelist_items()
        logger.debug(
            "Whitelist %s modality=%s project_dir=%s count=%d items=%s%s",
            action,
            modality,
            project_dir,
            len(items),
            items,
            f" delta={delta}" if delta else "",
        )

    def _load_whitelist_match_settings(self) -> None:
        if self._ds is None or self._ds.Modality is None:
            self._whitelist_match_settings = default_whitelist_match_settings()
            return
        project_dir = self._controller.model.storage_dir
        self._whitelist_match_settings = load_modality_whitelist_match_settings(project_dir, self._ds.Modality)
        self._apply_whitelist_match_settings_to_ui()
        self._log_whitelist_trace(
            "match_init",
            delta=describe_match_settings(self._whitelist_match_settings),
        )

    def _apply_whitelist_match_settings_to_ui(self) -> None:
        if not hasattr(self, "_whitelist_match_mode_var"):
            return
        settings = self._whitelist_match_settings
        self._whitelist_match_mode_var.set(match_mode_menu_label(settings.match_mode))
        self._sync_match_dropdown_state()

    def _sync_match_dropdown_state(self) -> None:
        """Enable match dropdown only when the whitelist has entries."""
        if not hasattr(self, "whitelist") or not hasattr(self, "_whitelist_match_mode_menu"):
            return
        has_items = self.whitelist.size() > 0
        self._whitelist_match_mode_menu.configure(state="normal" if has_items else "disabled")

    def _whitelist_match_settings_from_ui(self) -> OcrWhitelistMatchSettings:
        label = self._whitelist_match_mode_var.get()
        mode = self._match_mode_labels.get(label, OcrWhitelistMatchMode.STANDARD)
        return OcrWhitelistMatchSettings(match_mode=mode)

    def _on_whitelist_match_mode_changed(self, _choice: str | None = None) -> None:
        self._whitelist_match_settings = self._whitelist_match_settings_from_ui()
        self._whitelist_match_changed = True
        self._apply_whitelist_match_settings_to_ui()
        self._log_whitelist_trace(
            "match_mode",
            delta=describe_match_settings(self._whitelist_match_settings),
        )
        self._redraw_text_overlays_if_detected()

    def _redraw_text_overlays_if_detected(self) -> None:
        if not self.detected_text or not hasattr(self, "image_viewer"):
            return
        for frame_index in self.detected_text:
            self.draw_text_overlay(frame_index)
        self.image_viewer.refresh_current_image()
        self._refresh_ocr_toolbar_buttons()

    def _restore_whitelist_items(self, items: list[str]) -> None:
        if not hasattr(self, "whitelist"):
            return
        self.whitelist.delete(0, tk.END)
        for item in items:
            self.whitelist.insert(tk.END, item)
        self._sync_match_dropdown_state()

    def _series_interaction_allowed(self) -> bool:
        return not self._ui_rebuilding and not self._loading

    def _refresh_model_aware_toolbar_buttons(self) -> None:
        """Restore harmonize / blur / Clear presence from ORM and eligibility rules."""
        self._apply_ai_feature_visibility()

    def _set_series_interaction_enabled(self, enabled: bool) -> None:
        """Enable or disable Series View controls and the image viewer."""
        if not self.winfo_exists():
            return

        busy = not enabled
        widget_state = "disabled" if busy else "normal"
        listbox_state = tk.DISABLED if busy else tk.NORMAL

        for attr in (
            "detect_button",
            "blackout_button",
            "exclude_area_button",
            "ocr_remove_mode_menu",
            "edit_context_combo_box",
            "whitelist_entry",
            "whitelist_defaults_button",
            "whitelist_clear_button",
        ):
            widget = getattr(self, attr, None)
            if widget is not None:
                with contextlib.suppress(tk.TclError):
                    widget.configure(state=widget_state)

        if not busy:
            self._sync_match_dropdown_state()
            self._refresh_ocr_toolbar_buttons()
            self._refresh_model_aware_toolbar_buttons()
        else:
            for attr in ("remove_button", "remove_text_mode_menu"):
                widget = getattr(self, attr, None)
                if widget is not None:
                    with contextlib.suppress(tk.TclError):
                        widget.configure(state="disabled")
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
            if hasattr(self, "_whitelist_match_mode_menu"):
                with contextlib.suppress(tk.TclError):
                    self._whitelist_match_mode_menu.configure(state="disabled")

        if hasattr(self, "whitelist"):
            with contextlib.suppress(tk.TclError):
                self.whitelist.configure(state=listbox_state)

        if hasattr(self, "save_button") and busy:
            with contextlib.suppress(tk.TclError):
                self.save_button.configure(state="disabled")
        elif hasattr(self, "save_button"):
            self._refresh_save_button()

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
        self._present_series_view()
        self.lift()

    def _build_ui(self) -> None:
        assert self._ds is not None and self._frames is not None

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # SeriesView Frame:
        self._sv_frame = ctk.CTkFrame(self)
        self._sv_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self._sv_frame.grid_rowconfigure(0, weight=1)
        self._sv_frame.grid_columnconfigure(1, weight=1)

        # Left column: Whitelist only (Metadata assessment is a series dialog).
        self._sv_frame.grid_columnconfigure(0, minsize=280)
        self._whitelist_frame = ctk.CTkFrame(self._sv_frame, width=280)
        self._whitelist_frame.grid(row=0, column=0, sticky="nsew", padx=self.PAD, pady=self.PAD)
        self._whitelist_frame.grid_columnconfigure(0, weight=1)
        self._whitelist_frame.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(self._whitelist_frame, text=_("Whitelist"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=self.PAD, pady=(self.PAD, 2)
        )

        # Row 1: [Defaults] [Clear] [Match dropdown]
        toolbar = ctk.CTkFrame(self._whitelist_frame, fg_color="transparent")
        toolbar.grid(row=1, column=0, sticky="ew", padx=self.PAD, pady=(0, 2))
        toolbar.grid_columnconfigure(2, weight=1)
        self.whitelist_defaults_button = ctk.CTkButton(
            toolbar, text=_("Defaults"), width=10, command=self.whitelist_defaults_button_clicked
        )
        self.whitelist_defaults_button.grid(row=0, column=0, padx=(0, 2))
        self.whitelist_clear_button = ctk.CTkButton(toolbar, text=_("Clear"), width=10, command=self.clear_whitelist)
        self.whitelist_clear_button.grid(row=0, column=1, padx=(0, 2))

        self._match_mode_labels = match_mode_menu_labels()
        self._whitelist_match_mode_var = tk.StringVar(value=match_mode_menu_label(OcrWhitelistMatchMode.STANDARD))
        self._whitelist_match_mode_menu = ctk.CTkOptionMenu(
            toolbar,
            values=list(self._match_mode_labels.keys()),
            variable=self._whitelist_match_mode_var,
            width=10,
            command=self._on_whitelist_match_mode_changed,
        )
        self._whitelist_match_mode_menu.grid(row=0, column=2, sticky="ew")
        self._whitelist_match_mode_menu.configure(state="disabled")
        bind_hover_tooltip(
            self._whitelist_match_mode_menu,
            lambda: match_mode_description(
                self._match_mode_labels.get(
                    self._whitelist_match_mode_var.get(),
                    OcrWhitelistMatchMode.STANDARD,
                )
            ),
            parent=self,
        )

        # Row 2: entry
        self.whitelist_entry = ctk.CTkEntry(self._whitelist_frame)
        self.whitelist_entry.bind("<Return>", self.whitelist_button_clicked_or_entry_return)
        self.whitelist_entry.grid(row=2, column=0, sticky="ew", padx=self.PAD, pady=(2, 0))

        # Row 3: listbox + scrollbar
        list_frame = ctk.CTkFrame(self._whitelist_frame, fg_color="transparent")
        list_frame.grid(row=3, column=0, sticky="nsew", padx=self.PAD, pady=(0, self.PAD))
        list_frame.grid_columnconfigure(0, weight=1)
        list_frame.grid_rowconfigure(0, weight=1)
        scrollbar = ctk.CTkScrollbar(list_frame, orientation="vertical")
        self.whitelist = tk.Listbox(
            list_frame,
            border=0,
            yscrollcommand=scrollbar.set,
            bg="black",
            selectbackground="#004080",
            fg="white",
            selectforeground="white",
            highlightthickness=0,
            activestyle="none",
        )
        scrollbar.configure(command=self.whitelist.yview)
        self.whitelist.bind("<Delete>", self.whitelist_delete_keypressed)
        self.whitelist.bind("<BackSpace>", self.whitelist_delete_keypressed)
        self.whitelist.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        # ImageViewer:
        self.image_viewer = ImageViewer(
            self._sv_frame,
            self._frames,
            *self._viewer_wl_ww(),
            add_to_whitelist_callback=self.add_to_whitelist,
            regenerate_series_projections_callback=self.regenerate_series_projections,
            on_segmentation_toggle=self._on_segmentation_toggle,
            on_slice_index_changed=self._on_slice_index_changed,
            clear_callback=self.clear_ts_cache_button_clicked,
            on_annotate_mode_changed=self._on_annotate_mode_changed,
            on_annotate_stroke=self._on_annotate_stroke,
            on_annotate_stroke_end=self._on_annotate_stroke_end,
            on_annotate_undo=self._on_annotate_undo,
            on_annotate_new_label=self._on_annotate_new_label,
            on_annotate_import_segments=self._on_annotate_import_segments,
            on_annotate_target_changed=self._on_annotate_target_changed,
            on_annotate_requires_target=self._on_annotate_requires_target,
            on_exclude_rects_changed=self._refresh_save_button,
            series_projections=self._projections,
        )
        self.image_viewer.grid(row=0, column=1, sticky="nsew")
        self.image_viewer.detach_companion_stack()
        self.clear_ts_cache_button = self.image_viewer.clear_ts_cache_button
        self._bind_slice_navigation_keys()

        # Control Frame (toolbar row, status line, save row):
        self.control_frame = ctk.CTkFrame(self._sv_frame)
        self.control_frame.grid(row=1, columnspan=2, sticky="ew", padx=self.PAD, pady=self.PAD)
        # Button groups keep weight=0 so they do not compress; spacer column absorbs resize.
        self.control_frame.grid_columnconfigure(0, weight=0)
        self.control_frame.grid_columnconfigure(1, weight=1)
        self.control_frame.grid_columnconfigure(2, weight=0)

        text_edit_group = ctk.CTkFrame(self.control_frame, fg_color="transparent")
        self._text_edit_group = text_edit_group
        text_edit_group.grid(row=0, column=0, padx=(0, self.PAD), pady=self.PAD, sticky="w")
        self.edit_context_label = ctk.CTkLabel(text_edit_group, text=_("Edit Context") + ":")
        edit_context_labels = [
            edit_context_display_label(member)
            for member in edit_context_menu_values()
            if not (self.single_frame and member is OcrEditContext.SERIES)
        ]
        self._edit_context_var = tk.StringVar(value=edit_context_display_label(OcrEditContext.FRAME))
        self.edit_context_combo_box = ctk.CTkOptionMenu(
            text_edit_group,
            variable=self._edit_context_var,
            values=edit_context_labels,
            command=self.edit_context_change,
            dynamic_resizing=False,
            width=option_menu_width_for_labels(edit_context_labels),
        )
        # A single frame has no Frame/Series choice: hide Edit Context entirely.
        show_edit_context = edit_context_toolbar_visible(single_frame=self.single_frame)
        if show_edit_context:
            self.edit_context_label.grid(row=0, column=0, padx=(self.PAD, 2))
            self.edit_context_combo_box.grid(row=0, column=1, padx=(0, 8))
        detect_label = _("Detect")
        self.detect_button = ctk.CTkButton(
            text_edit_group,
            width=button_width_for_label(detect_label, minimum=self.BUTTON_WIDTH),
            text=detect_label,
            command=self.detect_text_button_clicked,
        )
        # Without Edit Context, Detect is the first control and needs the left pad.
        detect_pad_left = 0 if show_edit_context else self.PAD
        self.detect_button.grid(row=0, column=2, padx=(detect_pad_left, 8), pady=0)
        bind_hover_tooltip(
            self.detect_button,
            lambda: ocr_detect_tooltip(self._resolve_edit_context()),
        )
        remove_scope_label = ctk.CTkLabel(text_edit_group, text=_("Remove Scope") + ":")
        remove_scope_label.grid(row=0, column=3, padx=(0, 2))
        remove_mode_labels = list(ocr_remove_mode_menu_labels())
        self._ocr_remove_mode_var = tk.StringVar(
            value=ocr_remove_mode_display_label(OcrRemoveMode.NON_WHITELISTED)
        )
        self.ocr_remove_mode_menu = ctk.CTkOptionMenu(
            text_edit_group,
            variable=self._ocr_remove_mode_var,
            values=remove_mode_labels,
            command=self._on_ocr_remove_mode_changed,
            dynamic_resizing=False,
            width=option_menu_width_for_labels(remove_mode_labels),
        )
        self.ocr_remove_mode_menu.grid(row=0, column=4, padx=(0, 8))
        bind_hover_tooltip(
            self.ocr_remove_mode_menu,
            lambda: ocr_remove_mode_tooltip(self._selected_ocr_remove_mode()),
        )
        remove_label = _("Remove")
        self.remove_button = ctk.CTkButton(
            text_edit_group,
            width=button_width_for_label(remove_label, minimum=self.BUTTON_WIDTH),
            text=remove_label,
            command=self.remove_text_button_clicked,
            state="disabled",
        )
        self.remove_button.grid(row=0, column=5, padx=2, pady=0)
        bind_hover_tooltip(
            self.remove_button,
            lambda: ocr_remove_mode_tooltip(self._selected_ocr_remove_mode()),
        )
        removal_mode_labels = list(pixel_phi_removal_mode_menu_labels())
        self.remove_text_mode_var = tk.StringVar(
            value=pixel_phi_removal_mode_option_label(PixelPhiRemovalMode.BLACKOUT)
        )
        self.remove_text_mode_menu = ctk.CTkOptionMenu(
            text_edit_group,
            width=max(140, option_menu_width_for_labels(removal_mode_labels)),
            values=removal_mode_labels,
            variable=self.remove_text_mode_var,
        )
        self.remove_text_mode_menu.grid(row=0, column=6, padx=2, pady=0)
        # Remove stays visible but disabled until Detect identifies text for removal.
        self.remove_text_mode_menu.configure(state="disabled")
        blackout_label = _("Blackout Area")
        self.blackout_button = ctk.CTkButton(
            text_edit_group,
            width=button_width_for_label(blackout_label, minimum=self.BUTTON_WIDTH),
            text=blackout_label,
            command=self.blackout_button_clicked,
        )
        self.blackout_button.grid(row=0, column=7, padx=2, pady=0)
        bind_hover_tooltip(
            self.blackout_button,
            _(
                "Paint drawn rectangles black on the pixels. Draw a rectangle first, then click. "
                "Follows Edit Context (Frame or Series)."
            ),
        )
        exclude_label = _("Exclude Area")
        self.exclude_area_button = ctk.CTkButton(
            text_edit_group,
            width=button_width_for_label(exclude_label, minimum=self.BUTTON_WIDTH),
            text=exclude_label,
            command=self.exclude_area_button_clicked,
        )
        self.exclude_area_button.grid(row=0, column=8, padx=(2, 2), pady=0)
        bind_hover_tooltip(
            self.exclude_area_button,
            _(
                "Skip drawn rectangles during Detect Text and Remove. Pixels are not changed. "
                "Draw a rectangle first, then click. Click a dotted outline to delete it. "
                "Save Changes stores adds and removals for this modality "
                "(AI Batch: Enable Exclude Areas)."
            ),
        )
        metadata_label = _("Metadata")
        self.metadata_button = ctk.CTkButton(
            text_edit_group,
            width=button_width_for_label(metadata_label, minimum=self.BUTTON_WIDTH),
            text=metadata_label,
            command=self.metadata_assessment_button_clicked,
        )
        self.metadata_button.grid(row=0, column=9, padx=(2, self.PAD), pady=0)
        bind_hover_tooltip(
            self.metadata_button,
            _("View DICOM metadata for the current slice."),
            parent=self,
        )

        toolbar_spacer = ctk.CTkFrame(self.control_frame, fg_color="transparent", width=1, height=1)
        toolbar_spacer.grid(row=0, column=1, sticky="ew")

        harmonize_blur_group = ctk.CTkFrame(self.control_frame, fg_color="transparent")
        harmonize_blur_group.grid(row=0, column=2, padx=(0, self.PAD), pady=self.PAD, sticky="e")
        self.harmonize_button = ctk.CTkButton(
            harmonize_blur_group,
            width=160,
            text=harmonize_description_button_label(),
            command=self.harmonize_description_button_clicked,
        )
        self.harmonize_button.grid(row=0, column=0, padx=(self.PAD, 2), pady=0, sticky="e")
        self.blur_face_button = ctk.CTkButton(
            harmonize_blur_group,
            width=120,
            text=_("Blur Face"),
            command=self.blur_face_button_clicked,
        )
        self.blur_face_button.grid(row=0, column=1, padx=2, pady=0, sticky="e")
        self.blur_face_mode_var = tk.StringVar(value=face_blur_mode_menu_values()[0])
        self.blur_face_mode_menu = ctk.CTkOptionMenu(
            harmonize_blur_group,
            width=140,
            values=face_blur_mode_menu_values(),
            variable=self.blur_face_mode_var,
        )
        self.blur_face_mode_menu.grid(row=0, column=2, padx=(2, self.PAD), pady=0, sticky="e")
        # Harmonize / Face Blur presence is applied below (not greyed out). Clear lives in Segmentation panel.
        self.harmonize_button.grid_remove()
        self.blur_face_button.grid_remove()
        self.blur_face_mode_menu.grid_remove()

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
            columnspan=3,
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
            columnspan=2,
            padx=self.PAD,
            pady=(0, self.PAD),
            sticky="w",
        )

        save_label = _("Save Changes")
        self.save_button = ctk.CTkButton(
            self.control_frame,
            width=button_width_for_label(save_label, minimum=self.BUTTON_WIDTH),
            text=save_label,
            command=self.save_series_button_clicked,
        )
        self.save_button.grid(row=2, column=2, padx=self.PAD, pady=(0, self.PAD), sticky="e")
        self.save_button.configure(state="disabled")
        bind_hover_tooltip(self.save_button, self._save_changes_tooltip)
        self._refresh_series_processing_status()

        if self._ds is None or self._ds.Modality is None:
            logger.error("CRITICAL: Modality not found in dataset; whitelist not loaded")
        else:
            project_dir = self._controller.model.storage_dir
            whitelist = load_modality_whitelist(project_dir, self._ds.Modality)
            for item in whitelist:
                self.whitelist.insert(tk.END, item)
            self._sync_match_dropdown_state()
            self._log_whitelist_trace("init")
            self._load_whitelist_match_settings()
            self._load_saved_exclude_areas()

    def load_frames(self, series_path: Path) -> tuple[Dataset, np.ndarray, tuple[Path, ...]]:
        """Loads anatomical frames (no projection prefix in the scroll stack)."""
        loaded, frames, _projections, _geometry = self._load_series_data(series_path)
        return loaded.metadata, frames, loaded.slice_paths

    def _update_title(self):

        title = _("Series View")
        if self._ds:
            phi = self._controller.get_phi_by_anon_patient_id(self._ds.PatientID)
            if phi:
                desc = truncate_series_description(self._ds.get("SeriesDescription", ""))
                title += f" for {phi.patient_name} {self._ds.PatientID}"
                if desc:
                    title += f" {desc}"
                title += " "
        self.title(title)
        refresh_app_window_menu(self)

    def _series_context_line(self) -> str:
        geometry = self._series_geometry
        if geometry is None and not self._startup_layout:
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
        status = self._controller.get_series_processing_status(anon_uid)
        if status is None:
            self._series_status_label.configure(text="")
            return
        already_applied = self._controller.series_has_face_blur(anon_uid)
        include_face_blur = face_blur_status_applicable(
            self._face_blur_eligibility(),
            already_applied=already_applied,
        )
        self._series_status_label.configure(
            text=self._controller.format_series_processing_status(status, include_face_blur=include_face_blur),
        )

    def _harmonize_button_visible(self) -> bool:
        anon_uid = self._anon_series_uid()
        already_harmonized = anon_uid is not None and self._controller.series_is_harmonized(anon_uid)
        modality = getattr(self._ds, "Modality", None)
        return harmonize_button_visible(
            harmonize_models_ready=harmonize_allowed_for_modality(modality),
            modality=modality,
            already_harmonized=already_harmonized,
        )

    def _blur_face_toolbar_visible(self) -> bool:
        anon_uid = self._anon_series_uid()
        already_applied = anon_uid is not None and self._controller.series_has_face_blur(anon_uid)
        return blur_face_toolbar_visible(
            face_blur_models_ready=face_blur_allowed(),
            face_blur_already_applied=already_applied,
            is_head_series=self._workspace.is_head_series(self._ds),
        )

    def _clear_ts_cache_button_visible(self) -> bool:
        """Show Clear after Harmonize or when segment masks remain (must Clear before re-run)."""
        anon_uid = self._anon_series_uid()
        already_harmonized = anon_uid is not None and self._controller.series_is_harmonized(anon_uid)
        return clear_cache_button_visible(
            modality=getattr(self._ds, "Modality", None),
            already_harmonized=already_harmonized,
            has_segment_masks=self._seg_dir_likely_has_structures(),
        )

    def _set_toolbar_widget_present(self, widget: tk.Misc | None, present: bool) -> bool:
        """Show or hide a toolbar widget; return True when presence changed."""
        if widget is None:
            return False
        try:
            is_mapped = bool(widget.winfo_ismapped())
        except tk.TclError:
            return False
        if present and not is_mapped:
            with contextlib.suppress(tk.TclError):
                widget.grid()
                widget.configure(state="normal")
            return True
        if not present and is_mapped:
            with contextlib.suppress(tk.TclError):
                widget.grid_remove()
            return True
        if present and is_mapped and self._series_interaction_allowed():
            with contextlib.suppress(tk.TclError):
                widget.configure(state="normal")
        return False

    def _apply_ai_feature_visibility(self) -> None:
        changed = False
        if hasattr(self, "harmonize_button"):
            changed |= self._set_toolbar_widget_present(self.harmonize_button, self._harmonize_button_visible())
        if hasattr(self, "blur_face_button"):
            face_visible = self._blur_face_toolbar_visible()
            changed |= self._set_toolbar_widget_present(self.blur_face_button, face_visible)
            if hasattr(self, "blur_face_mode_menu"):
                changed |= self._set_toolbar_widget_present(self.blur_face_mode_menu, face_visible)
        if hasattr(self, "clear_ts_cache_button") and hasattr(self, "image_viewer"):
            present = self._clear_ts_cache_button_visible()
            was_present = False
            with contextlib.suppress(tk.TclError):
                was_present = bool(self.clear_ts_cache_button and self.clear_ts_cache_button.winfo_ismapped())
            self.image_viewer.set_clear_button_present(present)
            if present != was_present:
                changed = True
        if changed:
            self._adapt_window_to_toolbar()

    def update_status(self, message: str, *, debug_log: bool = False) -> None:
        """Show transient Series View operation status (row 2, below geometry)."""
        if debug_log:
            logger.debug("Series view: %s", message)
        else:
            logger.info("Series view: %s", message)
        if hasattr(self, "_status_label"):
            self._status_label.configure(text=message)
            self.update_idletasks()

    def _refresh_analysis_cache_ui(self, *, defer_render: bool = False) -> None:
        self._apply_fast_startup_chrome()
        self._refresh_segmentation_controls(defer_render=defer_render)

    def _seg_dir(self) -> Path:
        return self._workspace.seg_dir()

    def _seg_dir_likely_has_structures(self) -> bool:
        """Fast check for harmonized segmentation masks without reading NIfTI volumes."""
        seg_dir = self._seg_dir()
        if not seg_dir.is_dir():
            return False
        if read_primary_segment_voxels(seg_dir.parent):
            return True
        return any(seg_dir.glob("*.nii.gz"))

    def _segmentation_frame_offset(self) -> int:
        return 0

    def _cancel_structure_contour_job(self, name: str) -> None:
        cancel = self._structure_contour_cancel.pop(name, None)
        if cancel is not None:
            cancel.set()

    def _clear_structure_latch_state(self, name: str | None = None) -> None:
        if name is None:
            for latched in list(self._structure_contour_cancel):
                self._cancel_structure_contour_job(latched)
            self._structure_overlay_by_name.clear()
            self._structure_mask_by_name.clear()
            return
        self._cancel_structure_contour_job(name)
        self._structure_overlay_by_name.pop(name, None)
        self._structure_mask_by_name.pop(name, None)

    def _invalidate_structure_overlays(self) -> None:
        self._structure_contour_generation += 1
        self._clear_structure_latch_state()
        if hasattr(self, "image_viewer"):
            self.image_viewer.clear_active_segmentations()
            self.image_viewer.active_layers.discard(LayerType.SEGMENTATIONS)
            for frame_index in list(self.image_viewer.overlay_data.keys()):
                self.image_viewer.overlay_data[frame_index].segmentations = []
            self.image_viewer.clear_cache()
            self.image_viewer.load_and_display_image(self.image_viewer.current_image_index)

    def _push_merged_segmentation_overlays(self, *, defer_render: bool = False) -> None:
        if not hasattr(self, "image_viewer"):
            return
        visible = self._visible_segmentation_keys()
        filtered_structures = {
            name: by_slice
            for name, by_slice in self._structure_overlay_by_name.items()
            if name in visible
        }
        merged = merge_structure_overlays(filtered_structures)
        for key, by_slice in self._user_label_overlays.items():
            if key not in visible:
                continue
            for slice_index, segs in by_slice.items():
                merged.setdefault(slice_index, []).extend(segs)
        viewer_overlays = shift_overlays_to_viewer_frames(merged, frame_offset=0)
        if viewer_overlays:
            self.image_viewer.active_layers.add(LayerType.SEGMENTATIONS)
        else:
            self.image_viewer.active_layers.discard(LayerType.SEGMENTATIONS)
        for frame_index in list(self.image_viewer.overlay_data.keys()):
            self.image_viewer.overlay_data[frame_index].segmentations = []
        if viewer_overlays:
            self.image_viewer.set_segmentation_overlays(viewer_overlays)
        elif not defer_render:
            self.image_viewer.clear_cache()
            if self.image_viewer._startup_complete:
                self.image_viewer.load_and_display_image(self.image_viewer.current_image_index)

    def _visible_segmentation_keys(self) -> set[str]:
        """Keys whose overlays should be drawn.

        View: multi-select latch set. Annotate: only the exclusive paint target.
        """
        if self.image_viewer.get_annotate_mode() == "annotate":
            paint = self.image_viewer.get_paint_target_key()
            if paint is None:
                return set()
            if paint.startswith("ts:"):
                return {paint.split(":", 1)[1]}
            return {paint}
        return self.image_viewer.get_active_segmentation_names()

    def _anatomical_slice_for_viewer_frame(self, frame_index: int) -> int | None:
        slice_index = frame_index - self._segmentation_frame_offset()
        return slice_index if slice_index >= 0 else None

    def _ensure_structure_slice_contoured(self, name: str, slice_index: int) -> bool:
        """Contour one missing slice from the held mask. Returns True if cache changed."""
        if slice_index in self._structure_overlay_by_name.get(name, {}):
            return False
        mask = self._structure_mask_by_name.get(name)
        if mask is None:
            return False
        segs = contour_mask_slice(
            mask,
            slice_index,
            structure_name=name,
            color_bgr=color_bgr_for_structure(name),
        )
        cache = self._structure_overlay_by_name.setdefault(name, {})
        if segs:
            cache[slice_index] = segs
            return True
        # Remember empty slices so scrub does not re-contour them.
        cache[slice_index] = []
        return False

    def _on_slice_index_changed(self, frame_index: int) -> None:
        """ImageViewer slice/cine callback: overlays for the current frame."""
        self._ensure_segmentation_overlays_for_frame(frame_index)

    def metadata_assessment_button_clicked(self) -> None:
        """Open Metadata tree for the current slice (Detect / Remove PHI → Save)."""

        path = self._current_slice_path()
        ds = self._current_slice_dataset()
        if ds is None:
            return
        project_dir = self._controller.model.storage_dir
        whitelist: list[str] = []
        if hasattr(self, "whitelist"):
            whitelist = [str(t) for t in self.whitelist.get(0, tk.END)]
        MetadataAssessmentDialog(
            self,
            dataset=ds,
            dataset_path=path,
            project_dir=project_dir,
            modality=str(getattr(ds, "Modality", "") or "") or None,
            whitelist=whitelist,
            whitelist_match_settings=getattr(self, "_whitelist_match_settings", None),
        )

    def _current_slice_path(self) -> Path | None:
        """Path of the anatomical slice under the cine index, if loaded."""
        loaded = self._loaded
        if loaded is None:
            return None
        frame_index = (
            self.image_viewer.current_image_index
            if hasattr(self, "image_viewer")
            else 0
        )
        slice_index = self._anatomical_slice_for_viewer_frame(frame_index)
        if slice_index is None or slice_index >= len(loaded.slice_paths):
            return None
        return loaded.slice_paths[slice_index]

    def _current_slice_dataset(self) -> Dataset | None:
        """Load header for the anatomical slice under the cine index (no pixel dump)."""
        loaded = self._loaded
        if loaded is None:
            return None
        path = self._current_slice_path()
        if path is None:
            return loaded.metadata
        try:
            return dcmread(str(path), stop_before_pixels=True, force=True)
        except Exception:
            logger.exception("Could not read metadata for slice %s", path)
            return loaded.metadata

    def _ensure_segmentation_overlays_for_frame(self, frame_index: int) -> None:
        self._refresh_ocr_toolbar_buttons()
        slice_index = self._anatomical_slice_for_viewer_frame(frame_index)
        if slice_index is None:
            return
        visible = self._visible_segmentation_keys()
        changed = False
        for name in list(self._structure_mask_by_name):
            if name not in visible:
                continue
            changed = self._ensure_structure_slice_contoured(name, slice_index) or changed
        for key in visible:
            if not key.startswith("user:"):
                continue
            cache = self._user_label_overlays.get(key, {})
            if slice_index not in cache:
                self._recontour_after_paint(key, slice_index)
                changed = True
        if changed:
            self._push_merged_segmentation_overlays()

    def _start_structure_contour_background(
        self,
        name: str,
        mask: np.ndarray,
        *,
        prefer_slice: int,
        generation: int,
    ) -> None:
        self._cancel_structure_contour_job(name)
        cancel = threading.Event()
        self._structure_contour_cancel[name] = cancel
        color = color_bgr_for_structure(name)
        depth = int(mask.shape[0])
        contour_queue = self._structure_contour_queue

        def worker() -> None:
            try:
                remaining = [i for i in range(depth) if i != prefer_slice]
                # Contour current neighborhood first for scrub responsiveness.
                remaining.sort(key=lambda i: abs(i - prefer_slice))
                batch: dict[int, list[Segmentation]] = {}
                for slice_index in remaining:
                    if cancel.is_set():
                        return
                    segs = contour_mask_slice(
                        mask,
                        slice_index,
                        structure_name=name,
                        color_bgr=color,
                    )
                    if segs:
                        batch[slice_index] = segs
                    if len(batch) >= 8:
                        # Never call Tk from this thread — queue for the UI poller.
                        contour_queue.put((name, dict(batch), generation, cancel))
                        batch = {}
                if batch and not cancel.is_set():
                    contour_queue.put((name, dict(batch), generation, cancel))
            finally:
                # Sentinel: None marks job completion (UI drops cancel handle).
                contour_queue.put((name, None, generation, cancel))

        threading.Thread(
            target=worker,
            name=f"SegContour-{name}",
            daemon=True,
        ).start()
        self._kick_structure_contour_poll()

    def _kick_structure_contour_poll(self) -> None:
        """Schedule UI-thread drain of contour results (Tk is not thread-safe)."""
        if self._structure_contour_poll_after_id is not None:
            return
        if not self._widget_alive():
            return
        self._structure_contour_poll_after_id = self.after(
            self.LOAD_POLL_MS,
            self._poll_structure_contour_queue,
        )

    def _poll_structure_contour_queue(self) -> None:
        self._structure_contour_poll_after_id = None
        if not self._widget_alive():
            return
        updated = False
        while True:
            try:
                name, snapshot, generation, cancel = self._structure_contour_queue.get_nowait()
            except queue.Empty:
                break
            if cancel.is_set() or generation != self._structure_contour_generation:
                # Drop stale work; still release cancel handle on done sentinel.
                if snapshot is None and self._structure_contour_cancel.get(name) is cancel:
                    self._structure_contour_cancel.pop(name, None)
                continue
            if snapshot is None:
                if self._structure_contour_cancel.get(name) is cancel:
                    self._structure_contour_cancel.pop(name, None)
                continue
            if name not in self._structure_mask_by_name:
                continue
            cache = self._structure_overlay_by_name.setdefault(name, {})
            cache.update(snapshot)
            updated = True
        if updated:
            self._push_merged_segmentation_overlays()
        if self._structure_contour_cancel or not self._structure_contour_queue.empty():
            self._kick_structure_contour_poll()

    def _latch_structure_overlay(self, name: str, seg_dir: Path) -> None:
        """Load mask, paint current slice, contour the rest in the background."""
        self._cancel_structure_contour_job(name)
        color = color_bgr_for_structure(name)
        edited = None
        if self._annotate_session is not None:
            edited = self._annotate_session.ts_edits.get(name)
        mask = load_primary_segment_mask(seg_dir, name, edited_mask=edited)
        self._structure_mask_by_name[name] = mask
        frame_index = self.image_viewer.current_image_index if hasattr(self, "image_viewer") else 0
        slice_index = self._anatomical_slice_for_viewer_frame(frame_index)
        if slice_index is None:
            slice_index = 0
        source = "edited" if edited is not None else "ts"
        initial: dict[int, list[Segmentation]] = {}
        segs = contour_mask_slice(
            mask,
            slice_index,
            structure_name=name,
            color_bgr=color,
            source=source,
            editable=True,
            filled=False,
        )
        if segs:
            initial[slice_index] = segs
        else:
            initial[slice_index] = []
        self._structure_overlay_by_name[name] = initial
        generation = self._structure_contour_generation
        self._start_structure_contour_background(
            name,
            mask,
            prefer_slice=slice_index,
            generation=generation,
        )

    def _on_segmentation_toggle(self, name: str, active: bool) -> None:
        if name.startswith("user:"):
            if active:
                self._latch_user_label_overlay(name)
            else:
                self._user_label_overlays.pop(name, None)
            self._push_merged_segmentation_overlays()
            return
        if active:
            try:
                self._latch_structure_overlay(name, self._seg_dir())
            except FileNotFoundError:
                logger.warning("No on-disk masks for segmentation overlay %s; deactivating", name)
                self._clear_structure_latch_state(name)
                self._deactivate_segmentation_button(name)
                return
            except Exception:
                logger.exception("Failed to load segmentation overlay for %s", name)
                self._clear_structure_latch_state(name)
                self._deactivate_segmentation_button(name)
                return
        else:
            self._clear_structure_latch_state(name)
        self._push_merged_segmentation_overlays()

    def _latch_user_label_overlay(self, key: str) -> None:
        """Ensure contours for a custom user segment are available for the current slice."""
        session = self._ensure_annotate_session()
        if session is None or not key.startswith("user:"):
            return
        try:
            lid = int(key.split(":", 1)[1])
        except ValueError:
            return
        if lid not in session.label_map:
            return
        frame_index = self.image_viewer.current_image_index if hasattr(self, "image_viewer") else 0
        slice_index = self._anatomical_slice_for_viewer_frame(frame_index)
        if slice_index is None:
            slice_index = 0
        self._recontour_after_paint(key, slice_index)

    def _deactivate_segmentation_button(self, name: str) -> None:
        self.image_viewer._active_segmentation_names.discard(name)
        self.image_viewer._refresh_segmentation_button_styles()
        self._clear_structure_latch_state(name)
        self._push_merged_segmentation_overlays()

    def _segmentation_button_items(self) -> tuple[list[tuple[str, tuple[int, int, int]]], dict[str, str]]:
        """Custom user-label buttons then TS structure buttons (shared View/Annotate list)."""
        items: list[tuple[str, tuple[int, int, int]]] = []
        labels: dict[str, str] = {}
        session = self._ensure_annotate_session()
        if session is not None:
            for lid, entry in sorted(session.label_map.items()):
                key = f"user:{lid}"
                items.append((key, entry.color_bgr))
                labels[key] = entry.name
        seg_dir = self._seg_dir()
        if seg_dir.is_dir():
            present = collect_primary_segment_voxels(seg_dir)
            for name, _count in order_structures_by_voxels(present):
                items.append((name, color_bgr_for_structure(name)))
                labels[name] = structure_button_label(name)
        return items, labels

    def _refresh_segmentation_controls(self, *, defer_render: bool = False) -> None:
        if not hasattr(self, "image_viewer"):
            return
        self._ensure_annotate_session()
        seg_dir = self._seg_dir()
        items, labels = self._segmentation_button_items()
        if not items:
            if self._structure_overlay_by_name or self.image_viewer.get_active_segmentation_names():
                self._invalidate_structure_overlays()
            self.image_viewer.set_segmentation_title(mode=None)
            self.image_viewer.set_segmentation_structures([])
            self._sync_annotate_availability()
            return

        present = collect_primary_segment_voxels(seg_dir) if seg_dir.is_dir() else {}
        mode = read_cached_segmentation_mode(seg_dir.parent) if present else None
        self.image_viewer.set_segmentation_title(mode=mode)
        previous_active = self.image_viewer.get_active_segmentation_names()
        self.image_viewer.set_segmentation_structures(items, labels=labels)
        item_keys = {n for n, _ in items}
        still_ts = previous_active & set(present)
        still_user = {n for n in previous_active if n.startswith("user:") and n in item_keys}
        view_user = {n for n in self.image_viewer._view_latch_names if n.startswith("user:") and n in item_keys}
        still_user |= view_user
        still = still_ts | still_user
        self.image_viewer._active_segmentation_names = still
        self.image_viewer._view_latch_names = (
            {n for n in self.image_viewer._view_latch_names if n in item_keys} | still_user
        )
        self.image_viewer._refresh_segmentation_button_styles()
        # Reload latched masks from disk on refresh (Harmonize/Clear) — never on slice change.
        self._structure_contour_generation += 1
        self._clear_structure_latch_state()
        self._user_label_overlays.clear()
        for name in still_ts:
            try:
                self._latch_structure_overlay(name, seg_dir)
            except Exception:
                logger.exception("Failed to refresh segmentation overlay for %s", name)
                self.image_viewer._active_segmentation_names.discard(name)
        for key in still_user:
            self._latch_user_label_overlay(key)
        self.image_viewer._refresh_segmentation_button_styles()
        self._push_merged_segmentation_overlays(defer_render=defer_render)
        self._sync_annotate_availability()
        options = [(self.image_viewer._paint_key_for_button(n), labels.get(n, n)) for n, _ in items]
        self.image_viewer.set_paint_targets(options, active_key=self.image_viewer.get_paint_target_key())
        if self.image_viewer.get_annotate_mode() == "annotate":
            target = self.image_viewer.get_paint_target_key()
            if target and target.startswith("ts:"):
                self.image_viewer._select_annotate_segment(target.split(":", 1)[1])
            elif target and target.startswith("user:"):
                self.image_viewer._select_annotate_segment(target)

    def _refresh_paint_target_options(self) -> None:
        """Rebuild segment buttons after annotation label changes."""
        if not hasattr(self, "image_viewer"):
            return
        previous_active = self.image_viewer.get_active_segmentation_names()
        previous_target = self.image_viewer.get_paint_target_key()
        items, labels = self._segmentation_button_items()
        self.image_viewer.set_segmentation_structures(items, labels=labels)
        item_keys = {n for n, _ in items}
        still_ts = {n for n in previous_active if not n.startswith("user:") and n in item_keys}
        still_user = {n for n in previous_active if n.startswith("user:") and n in item_keys}
        still_user |= {n for n in self.image_viewer._view_latch_names if n.startswith("user:") and n in item_keys}
        still = still_ts | still_user
        self.image_viewer._active_segmentation_names = still
        self.image_viewer._view_latch_names = (
            {n for n in self.image_viewer._view_latch_names if n in item_keys} | still_user
        )
        options = [(self.image_viewer._paint_key_for_button(n), labels.get(n, n)) for n, _ in items]
        if self.image_viewer.get_annotate_mode() == "annotate":
            target = previous_target
            if target is None and still:
                # Prefer an already-active chip, else first button.
                first_active = sorted(still)[0]
                target = self.image_viewer._paint_key_for_button(first_active)
            elif target is None and items:
                target = self.image_viewer._paint_key_for_button(items[0][0])
            self.image_viewer.set_paint_targets(options, active_key=target)
            if target and target.startswith("ts:"):
                self.image_viewer._select_annotate_segment(target.split(":", 1)[1])
            elif target and target.startswith("user:"):
                self.image_viewer._select_annotate_segment(target)
        else:
            self.image_viewer.set_paint_targets(options, active_key=previous_target)
            self.image_viewer._refresh_segmentation_button_styles()
            seg_dir = self._seg_dir()
            for name in still_ts:
                if name in self._structure_overlay_by_name:
                    continue
                try:
                    self._latch_structure_overlay(name, seg_dir)
                except Exception:
                    logger.exception("Failed to re-latch %s after button rebuild", name)
                    self.image_viewer._active_segmentation_names.discard(name)
            for key in still_user:
                if key not in self._user_label_overlays:
                    self._latch_user_label_overlay(key)
            self._push_merged_segmentation_overlays()

    def _on_series_description_updated(self) -> None:
        self._update_title()
        self._series_geometry = None
        self._face_blur_eligibility_cache = None
        self._face_blur_eligibility_geometry = None
        self._refresh_analysis_cache_ui()
        self._refresh_series_processing_status()
        # PHI Index Harmonized column is study-level ORM state; refresh so Accept is visible.
        index = find_dataset_view_parent(self)
        if index is not None:
            with contextlib.suppress(tk.TclError):
                index._update_tree_from_phi_index()

    def _face_blur_eligibility(self) -> FaceBlurEligibility:
        already_applied = (
            self._controller.series_has_face_blur(str(self._ds.SeriesInstanceUID))
            if self._ds is not None
            else False
        )
        eligibility = self._workspace.face_blur_eligibility(
            ds=self._ds,
            already_applied=already_applied,
        )
        self._series_geometry = self._workspace.ensure_geometry(ds=self._ds)
        return eligibility

    def _ocr_results_available_for_edit_context(self) -> bool:
        """True when Detect Text has left OCR overlays usable by Remove Text for the edit context."""
        if not hasattr(self, "image_viewer"):
            return False
        overlay_ocr_by_frame = {
            frame_i: self.filter_text_data(frame_i)
            for frame_i in self.detected_text
        }
        return ocr_results_available_for_edit_context(
            self.edit_context,
            current_frame_index=self.image_viewer.current_image_index,
            overlay_ocr_by_frame=overlay_ocr_by_frame,
        )

    def _refresh_ocr_toolbar_buttons(self) -> None:
        """Enable Remove (+ removal-mode menu) only when text is identified for removal."""
        enabled = ocr_remove_enabled(
            interaction_allowed=self._series_interaction_allowed(),
            detecting=self._ocr_detecting,
            results_available=self._ocr_results_available_for_edit_context(),
        )
        state = "normal" if enabled else "disabled"
        for attr in ("remove_button", "remove_text_mode_menu"):
            widget = getattr(self, attr, None)
            if widget is None:
                continue
            with contextlib.suppress(tk.TclError):
                widget.configure(state=state)

    def _selected_face_blur_mode(self) -> FaceBlurMode:
        if not hasattr(self, "blur_face_mode_var"):
            return FaceBlurMode.GAUSSIAN
        return face_blur_mode_from_menu_label(self.blur_face_mode_var.get())

    def clear_whitelist(self):
        self.whitelist.delete(0, "end")
        self.whitelist_entry.delete(0, ctk.END)
        self.whitelist_entry.focus_set()
        self._whitelist_changed = True
        self._log_whitelist_trace("clear")
        self._sync_match_dropdown_state()

    def add_to_whitelist(self, text: str):
        whitelist = self.whitelist.get(0, tk.END)
        try:
            ndx = whitelist.index(text)
            self.whitelist.select_set(ndx)
        except ValueError:
            self.whitelist.insert(0, text)
            self._whitelist_changed = True
            self._log_whitelist_trace("add", delta=f"+{text}")
            self._sync_match_dropdown_state()

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

        removed = [str(self.whitelist.get(i)) for i in selected_indices]
        # Delete items in reverse order to avoid index issues.
        for i in reversed(selected_indices):
            self.whitelist.delete(i)
            self.whitelist.select_set(i - 1)
            self.whitelist.activate(i - 1)

        self._whitelist_changed = True
        self._log_whitelist_trace("remove", delta=f"-{removed}")
        self._sync_match_dropdown_state()

    def _resolve_edit_context(self) -> OcrEditContext:
        if hasattr(self, "_edit_context_var"):
            self.edit_context = normalize_edit_context(self._edit_context_var.get())
        return self.edit_context

    def edit_context_change(self, choice):
        logger.info(f"Edit Context changed to: {choice}")
        self.edit_context = normalize_edit_context(choice)
        self.image_viewer.set_overlay_propagation(self.edit_context is OcrEditContext.SERIES)
        self._refresh_ocr_toolbar_buttons()

    def regenerate_series_projections(self) -> None:
        if self._frames is not None and not self.single_frame:
            logger.info("Regenerate Series Projections")
            self._projections = compute_series_projections(self._frames)
            if hasattr(self, "image_viewer"):
                self.image_viewer.set_series_projections(self._projections)
                if self.image_viewer._is_projection_mode():
                    self.image_viewer.refresh_current_image()

    def process_single_frame_ocr(self, frame_index: int):
        """Performs OCR on a single frame (sync fallback — prefer background detect_text job)."""
        if self._ds is None:
            return
        frame = self.image_viewer.images[frame_index]
        results = self._workspace.detect_text_on_frame_sync(ds=self._ds, frame=frame)
        if results:
            logger.debug(f"OCR Results:\n{pformat(results)}")
            self._apply_ocr_detections_for_frame(frame_index, results)

    def _on_ocr_job_tick(self, work_state: WorkState) -> None:
        if not self._widget_alive():
            return
        frame_index, status, _done, result = work_state.snapshot_progress()
        if status:
            self.update_status(status, debug_log=True)
        if self.edit_context is OcrEditContext.SERIES and frame_index != self._ocr_poll_frame_index:
            self._ocr_poll_frame_index = frame_index
            self.image_viewer.load_and_display_image(frame_index)
        if isinstance(result, dict):
            for fi, texts in result.items():
                frame_i = int(fi)
                if self.detected_text.get(frame_i) is not texts:
                    self._apply_ocr_detections_for_frame(frame_i, texts)

    def _apply_ocr_detections_for_frame(self, frame_i: int, texts: list) -> None:
        # Fresh detections are current for the selected Remove target again.
        self.detected_text[frame_i] = texts
        self._ocr_transcript_by_frame[frame_i] = [t.text for t in texts if (t.text or "").strip()]
        logger.info(
            "Series View OCR applied %d detection(s) to frame_index=%s",
            len(texts),
            frame_i,
        )
        self.draw_text_overlay(frame_i)

    def _apply_ocr_detections_result(self, result: dict) -> None:
        for fi, texts in result.items():
            self._apply_ocr_detections_for_frame(int(fi), texts)

    def _on_ocr_job_done(self, _algorithm: Algorithm | None, work_state: WorkState) -> None:
        if not self._widget_alive():
            return
        _frame_index, _status, _done, result = work_state.snapshot_progress()
        logger.info("Series View OCR job done error=%s", work_state.error)
        self._ocr_detecting = False
        if work_state.error:
            self.update_status(_("Text detection failed") + f": {work_state.error}")
            self._refresh_ocr_toolbar_buttons()
            return
        detections_by_frame: dict[int, list[OCRText]] = {}
        if isinstance(result, dict):
            self._apply_ocr_detections_result(result)
            detections_by_frame = {
                int(fi): list(texts) for fi, texts in result.items() if texts
            }
            if hasattr(self, "image_viewer") and result:
                if self.edit_context is OcrEditContext.FRAME:
                    detected_frame = int(next(iter(result)))
                    if detected_frame != self.image_viewer.current_image_index:
                        self.image_viewer.load_and_display_image(detected_frame)
                    else:
                        self.image_viewer.refresh_current_image()
                else:
                    self.image_viewer.refresh_current_image()
        frames_scanned = None
        if self.edit_context is OcrEditContext.SERIES and hasattr(self, "image_viewer"):
            frames_scanned = self.image_viewer.num_images
        exclude_rects_by_frame: dict[int, list[UserRectangle]] = {}
        if hasattr(self, "image_viewer"):
            for frame_i in detections_by_frame:
                if frame_i in self.image_viewer.overlay_data:
                    rects = list(self.image_viewer.overlay_data[frame_i].exclude_rects)
                    if rects:
                        exclude_rects_by_frame[frame_i] = rects
        status = format_ocr_detection_complete_status(
            detections_by_frame,
            whitelist=self.get_whitelist_set() if hasattr(self, "whitelist") else [],
            whitelist_match_settings=getattr(self, "_whitelist_match_settings", None),
            exclude_rects_by_frame=exclude_rects_by_frame,
            frames_scanned=frames_scanned,
            remove_mode=self._selected_ocr_remove_mode(),
        )
        self.update_status(status, debug_log=True)
        work_state.reset()
        self._ocr_poll_frame_index = -1
        self._refresh_ocr_toolbar_buttons()

    def _start_ocr_background_job(self) -> None:
        if self._ds is None or self._frames is None:
            return
        edit_context = self._resolve_edit_context()
        logger.info("Series View starting OCR background job edit_context=%s", edit_context)
        wl, ww = self._dicom_wl or 0.0, self._dicom_ww or 0.0
        if self._ds is not None:
            wl, ww = get_wl_ww(self._ds)
        frame_index = self.image_viewer.current_image_index if hasattr(self, "image_viewer") else 0
        ocr_source = self.image_viewer.images if hasattr(self, "image_viewer") else None
        options = self._workspace.prepare_ocr_job(
            self._ocr_work_state,
            ds=self._ds,
            frames=self._frames,
            slice_paths=self._slice_paths,
            default_window=(wl, ww),
            single_frame=self.single_frame,
            edit_context=edit_context,
            frame_index=frame_index,
            ocr_source_images=ocr_source,
        )
        if edit_context is not OcrEditContext.FRAME:
            self.detected_text.clear()
            if hasattr(self, "image_viewer"):
                self.image_viewer.clear_text_overlays()
        self._ocr_detecting = True
        self._refresh_ocr_toolbar_buttons()
        self._ocr_poll_frame_index = -1
        if edit_context is OcrEditContext.FRAME:
            self.update_status(_("Detecting text in current image") + "…", debug_log=True)
        else:
            self.update_status(_("Detecting text in all images") + "…", debug_log=True)

        def _worker() -> None:
            self._workspace.run_ocr_job(self._ocr_work_state, options)

        start_background_job(
            self,
            work_state=self._ocr_work_state,
            algorithm=Algorithm.REMOVE_PIXEL_PHI,
            worker_target=_worker,
            on_tick=self._on_ocr_job_tick,
            on_done=self._on_ocr_job_done,
        )

    def _selected_ocr_remove_mode(self) -> OcrRemoveMode:
        if hasattr(self, "_ocr_remove_mode_var"):
            self.ocr_remove_mode = normalize_ocr_remove_mode(self._ocr_remove_mode_var.get())
        return self.ocr_remove_mode

    def _on_ocr_remove_mode_changed(self, _choice: str | None = None) -> None:
        # Changing Remove Scope only re-filters existing detections.
        self._redraw_text_overlays_if_detected()
        self._refresh_ocr_toolbar_buttons()

    def filter_text_data(self, frame_index: int) -> list[OCRText]:
        """Hide boxes that the current remove target would not remove."""
        if frame_index not in self.detected_text:
            return []
        exclude_rects: list[UserRectangle] = []
        if hasattr(self, "image_viewer") and frame_index in self.image_viewer.overlay_data:
            exclude_rects = list(self.image_viewer.overlay_data[frame_index].exclude_rects)
        return filter_series_view_ocr_overlay(
            self.detected_text[frame_index],
            remove_mode=self._selected_ocr_remove_mode(),
            whitelist=self.get_whitelist_set() if hasattr(self, "whitelist") else [],
            whitelist_match_settings=getattr(self, "_whitelist_match_settings", None),
            exclude_rects=exclude_rects,
        )

    def draw_text_overlay(self, frame_index: int):
        """Draws text boxes on the overlay for the given frame, based on filtered text_data."""
        filtered_text_data = self.filter_text_data(frame_index)
        raw_detections = self.detected_text.get(frame_index, [])
        raw_count = len(raw_detections)
        if raw_count != len(filtered_text_data):
            filtered_texts = {item.text for item in filtered_text_data}
            filtered_out = [item.text for item in raw_detections if item.text not in filtered_texts]
            logger.info(
                "Series View OCR overlay frame_index=%s: %d stored, %d drawn; filtered: %s",
                frame_index,
                raw_count,
                len(filtered_text_data),
                filtered_out,
            )
        self.image_viewer.set_text_overlay_data(frame_index, filtered_text_data)

    def detect_text_for_series(self):
        """Detects text in all frames via background job (SERIES edit context)."""
        self._start_ocr_background_job()

    def detect_text_button_clicked(self):
        if self._ocr_detecting or not self._series_interaction_allowed():
            return
        logger.info("Detect Text clicked edit_context=%s", self._resolve_edit_context())
        self._start_ocr_background_job()

    def remove_text_from_single_frame(self, frame_index: int, ocr_texts: list[OCRText]):
        logger.debug(f"Remove {len(ocr_texts)} words from frame {frame_index}")
        exclude_rects: list[UserRectangle] = []
        if frame_index in self.image_viewer.overlay_data:
            exclude_rects = list(self.image_viewer.overlay_data[frame_index].exclude_rects)
        raw_frame = self.image_viewer.images[frame_index]
        windowed_frame = (
            ocr_image_for_frame(self._ds, raw_frame)
            if self._ds
            else apply_windowing(self.image_viewer.current_wl, self.image_viewer.current_ww, raw_frame)
        )
        removal_mode = normalize_pixel_phi_removal_mode(self.remove_text_mode_var.get())
        result = self._workspace.remove_ocr_from_frame(
            raw_frame=raw_frame,
            windowed_frame=windowed_frame,
            ocr_texts=ocr_texts,
            exclude_rects=exclude_rects,
            removal_mode=removal_mode,
        )
        if result is None:
            return
        if result.removed_labels:
            pending = self._removed_pixel_phi_by_frame.setdefault(frame_index, [])
            for label in result.removed_labels:
                if label not in pending:
                    pending.append(label)
        self.image_viewer.images[frame_index] = result.frame
        self._pixel_phi_dirty = True
        self._refresh_save_button()
        cached = self.detected_text.get(frame_index, [])
        if cached:
            self.detected_text[frame_index] = [
                item for item in cached if (item.text, item.get_bounding_box()) not in result.removed_keys
            ]

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
        edit_context = self._resolve_edit_context()
        logger.debug(f"Removing text, current edit context={edit_context}")

        if edit_context is OcrEditContext.FRAME:
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

        self._refresh_ocr_toolbar_buttons()

        # TODO: Remove all in PROJECT if modality and image size constant

    def blackout_areas_in_single_frame(self, frame_index: int, user_rects: list[UserRectangle]):
        logger.debug(f"Blackout {len(user_rects)} rects from frame {frame_index}")
        self._workspace.blackout_rects_on_frame(self.image_viewer.images[frame_index], user_rects)
        self._pixel_phi_dirty = True
        self._refresh_save_button()

    def blackout_areas_in_series(self) -> int:
        """Black out pending user rects across the series; return rects applied.

        With no pending rects this is a no-op (0) — it must not clear caches or
        replay the series frame by frame.
        """
        total_frames = self.image_viewer.num_images
        pending = sum(
            len(self.image_viewer.overlay_data[i].user_rects)
            for i in range(total_frames)
            if i in self.image_viewer.overlay_data
        )
        if not pending:
            return 0
        applied = 0
        self.image_viewer.clear_cache()
        for i in range(total_frames):
            if i not in self.image_viewer.overlay_data:
                continue
            user_rects = self.image_viewer.overlay_data[i].user_rects
            if user_rects:
                applied += len(user_rects)
                self.blackout_areas_in_single_frame(i, user_rects)
            self.image_viewer.load_and_display_image(i)
            self.update()
        self.image_viewer.clear_cache()
        self.regenerate_series_projections()
        self.image_viewer.load_and_display_image(0)
        return applied

    def blackout_button_clicked(self):
        logger.debug(f"Blackout text, current edit context[{self.edit_context}]")

        if self._resolve_edit_context() is OcrEditContext.FRAME:
            ndx = self.image_viewer.current_image_index
            user_rects = self.image_viewer.overlay_data[ndx].user_rects
            if not user_rects:
                logger.warning("No blackout user rect has been defined in current frame to blackout")
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
            applied = self.blackout_areas_in_series()
            if not applied:
                logger.warning("No blackout user rect has been defined in series to blackout")
                self.update_status(_("No blackout area(s) in series"))
                return
            self.update_status(_("Blackout applied to all images"))

    def _commit_user_rects_to_exclude(self, frame_index: int) -> int:
        """Move pending user_rects on frame_index onto exclude_rects. Returns count moved."""
        if frame_index not in self.image_viewer.overlay_data:
            return 0
        return commit_user_rects_to_exclude(self.image_viewer.overlay_data[frame_index])

    def exclude_areas_in_single_frame(self, frame_index: int) -> int:
        moved = self._commit_user_rects_to_exclude(frame_index)
        if moved and frame_index in self.detected_text:
            self.draw_text_overlay(frame_index)
        return moved

    def exclude_areas_in_series(self) -> int:
        total = 0
        for i in range(self.image_viewer.num_images):
            total += self._commit_user_rects_to_exclude(i)
            if i in self.detected_text:
                self.draw_text_overlay(i)
        self.image_viewer.clear_cache()
        self.image_viewer.refresh_current_image()
        return total

    def exclude_area_button_clicked(self):
        """Convert drawn user rectangles into Detect/Remove exclude zones (no pixel change)."""
        edit_context = self._resolve_edit_context()
        logger.debug("Exclude Area clicked edit_context=%s", edit_context)

        if edit_context is OcrEditContext.FRAME:
            ndx = self.image_viewer.current_image_index
            user_rects = (
                self.image_viewer.overlay_data[ndx].user_rects
                if ndx in self.image_viewer.overlay_data
                else []
            )
            if not user_rects:
                logger.warning("No user rect defined in current frame to exclude")
                self.update_status(_("No area(s) drawn in current frame to exclude"))
                return
            moved = self.exclude_areas_in_single_frame(ndx)
            self.image_viewer.refresh_current_image()
            self.update_status(
                _("Excluded {count} area(s) from text detection on current image").format(count=moved)
            )
            self._refresh_save_button()
            return
        # Ensure SERIES propagation: if only the current frame has pending draws,
        # copy them to every frame before committing (cine US measurement panels).
        ndx = self.image_viewer.current_image_index
        current_pending = (
            list(self.image_viewer.overlay_data[ndx].user_rects)
            if ndx in self.image_viewer.overlay_data
            else []
        )
        if current_pending:
            for i in range(self.image_viewer.num_images):
                if i == ndx:
                    continue
                if i not in self.image_viewer.overlay_data:
                    self.image_viewer.overlay_data[i] = OverlayData()
                if not self.image_viewer.overlay_data[i].user_rects:
                    self.image_viewer.overlay_data[i].user_rects = [
                        UserRectangle(top_left=r.top_left, bottom_right=r.bottom_right)
                        for r in current_pending
                    ]
        moved = self.exclude_areas_in_series()
        if not moved:
            self.update_status(_("No area(s) drawn to exclude"))
            return
        self.update_status(
            _("Excluded {count} area(s) from text detection across series").format(count=moved)
        )
        self._refresh_save_button()

    def _frame_size(self, frame_index: int) -> tuple[int, int]:
        if not hasattr(self, "image_viewer"):
            return (1, 1)
        frame = self.image_viewer.images[frame_index]
        height, width = frame.shape[:2]
        return int(width), int(height)

    def _all_active_exclude_normalized(self) -> list[dict]:
        if not hasattr(self, "image_viewer"):
            return []
        seen: set[tuple[float, float, float, float]] = set()
        unique: list[dict] = []
        for frame_i, overlay in self.image_viewer.overlay_data.items():
            if not overlay.exclude_rects:
                continue
            width, height = self._frame_size(frame_i)
            for rect in normalize_user_rects(overlay.exclude_rects, width=width, height=height):
                key = self._exclude_rect_key(rect)
                if key in seen:
                    continue
                seen.add(key)
                unique.append(rect)
        return unique

    @staticmethod
    def _exclude_rect_key(rect: dict) -> tuple[float, float, float, float]:
        return (
            round(float(rect["x1"]), 4),
            round(float(rect["y1"]), 4),
            round(float(rect["x2"]), 4),
            round(float(rect["y2"]), 4),
        )

    def _exclude_areas_dirty(self) -> bool:
        return exclude_rects_fingerprint(self._all_active_exclude_normalized()) != self._saved_exclude_fingerprint

    def _save_changes_pending(self) -> bool:
        return bool(self._pixel_phi_dirty or self._exclude_areas_dirty())

    def _save_changes_tooltip(self) -> str:
        pixel_dirty = bool(self._pixel_phi_dirty)
        exclude_dirty = self._exclude_areas_dirty()
        if not pixel_dirty and not exclude_dirty:
            return _("No unsaved pixel or exclude area changes.")
        parts: list[str] = []
        if pixel_dirty:
            parts.append(_("Pixel edits (remove or blackout) will be written to this series."))
        if exclude_dirty:
            if pixel_dirty:
                parts.append(
                    _("Exclude area add/remove changes will be saved for this modality (AI Batch: Enable Exclude Areas).")
                )
            else:
                parts.append(
                    _(
                        "Exclude area add/remove changes will be saved for this modality. "
                        "Pixels are not changed. AI Batch: Enable Exclude Areas."
                    )
                )
        return " ".join(parts)

    def _refresh_save_button(self) -> None:
        if not hasattr(self, "save_button"):
            return
        enabled = self._save_changes_pending() and self._series_interaction_allowed()
        with contextlib.suppress(tk.TclError):
            self.save_button.configure(state="enabled" if enabled else "disabled")

    def _load_saved_exclude_areas(self) -> None:
        if self._ds is None or not hasattr(self, "image_viewer"):
            return
        project_dir = self._controller.model.storage_dir
        modality = str(self._ds.get("Modality", "") or "")
        stored = load_project_exclude_rects(project_dir, modality)
        self._saved_exclude_fingerprint = exclude_rects_fingerprint(stored)
        width, height = self._frame_size(self.image_viewer.current_image_index)
        loaded = modality_exclude_rects_for_series(project_dir, modality, width=width, height=height)
        if loaded:
            self._apply_loaded_exclude_rects(loaded)
            self._redraw_text_overlays_if_detected()
        self._refresh_save_button()

    def _apply_loaded_exclude_rects(self, rects: list[UserRectangle]) -> None:
        if not rects or not hasattr(self, "image_viewer"):
            return
        for frame_i in range(self.image_viewer.num_images):
            if frame_i not in self.image_viewer.overlay_data:
                self.image_viewer.overlay_data[frame_i] = OverlayData()
            self.image_viewer.overlay_data[frame_i].exclude_rects = [
                UserRectangle(top_left=r.top_left, bottom_right=r.bottom_right) for r in rects
            ]
        self.image_viewer.refresh_current_image()

    def _on_harmonize_closed(self, _outcome: HarmonizeBatchOutcome) -> None:
        """Re-enable Series View after Harmonize closes (Accept, Cancel, or destroy)."""
        self._harmonize_view = None
        if not self.winfo_exists() or getattr(self, "_destroyed", False) or getattr(self, "_closing", False):
            return
        self._set_series_interaction_enabled(True)
        self._series_geometry = None
        self._face_blur_eligibility_cache = None
        self._face_blur_eligibility_geometry = None
        self._refresh_analysis_cache_ui()
        self._refresh_series_processing_status()

    def harmonize_description_button_clicked(self):
        if not self._harmonize_button_visible():
            return

        def _before_open() -> None:
            with contextlib.suppress(tk.TclError):
                self.harmonize_button.grid_remove()
            self._set_series_interaction_enabled(False)

        view = launch_harmonize_description(
            self,
            series_path=self._series_path,
            ds=self._ds,
            anon_model=self._controller.anonymizer.model,
            fonts=self._fonts,
            mappings_dir=self._controller.model.mappings_dir(),
            existing_view=getattr(self, "_harmonize_view", None),
            on_series_description_updated=self._on_series_description_updated,
            on_closed=self._on_harmonize_closed,
            on_before_open=_before_open,
        )
        if view is not None:
            self._harmonize_view = view

    def _cache_dir(self) -> Path:
        return self._workspace.cache_dir()

    def _ensure_annotate_session(self) -> AnnotateSession | None:
        self._annotate_session = self._workspace.ensure_annotate_session(
            existing=self._annotate_session,
            frames=self._frames,
        )
        return self._annotate_session

    def _sync_annotate_availability(self) -> None:
        if not hasattr(self, "image_viewer"):
            return
        session = self._ensure_annotate_session()
        self.image_viewer.set_annotate_enabled(session is not None)

    def _on_annotate_import_segments(self) -> None:
        """Import researcher NIfTI/NRRD masks into user annotation labels."""

        session = self._ensure_annotate_session()
        if session is None:
            messagebox.showinfo(
                title=_("Import Segments"),
                message=_("Could not create annotation geometry for this series."),
                parent=self,
            )
            return

        profile_labels = {
            _("Auto-detect"): ImportProfile.AUTO,
            _("Multi-label volume"): ImportProfile.MULTILABEL,
            _("ITK-SNAP (+ .label)"): ImportProfile.ITK_SNAP,
            _("nnU-Net (+ dataset.json)"): ImportProfile.NNUNET,
            _("Binary masks"): ImportProfile.BINARY_MASKS,
            _("TotalSegmentator folder"): ImportProfile.FOLDER_TS,
        }

        dlg = ctk.CTkToplevel(self)
        dlg.title(_("Import Segments"))
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)
        choice: dict[str, ImportProfile | None] = {"profile": ImportProfile.AUTO}

        ctk.CTkLabel(dlg, text=_("Format preset") + ":").grid(row=0, column=0, padx=12, pady=(12, 4), sticky="w")
        preset_var = ctk.StringVar(value=_("Auto-detect"))
        preset_menu = ctk.CTkOptionMenu(dlg, variable=preset_var, values=list(profile_labels.keys()), width=220)
        preset_menu.grid(row=1, column=0, padx=12, pady=(0, 8), sticky="ew")

        def _cancel() -> None:
            choice["profile"] = None
            dlg.destroy()

        def _pick_files() -> None:
            choice["profile"] = profile_labels.get(preset_var.get(), ImportProfile.AUTO)
            dlg.destroy()

        def _pick_folder() -> None:
            choice["profile"] = ImportProfile.FOLDER_TS
            dlg.destroy()

        btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_row.grid(row=2, column=0, padx=12, pady=(4, 12), sticky="ew")
        ctk.CTkButton(btn_row, text=_("Choose files…"), width=120, command=_pick_files).grid(
            row=0, column=0, padx=(0, 6)
        )
        ctk.CTkButton(btn_row, text=_("Choose folder…"), width=120, command=_pick_folder).grid(
            row=0, column=1, padx=(0, 6)
        )
        ctk.CTkButton(btn_row, text=_("Cancel"), width=80, command=_cancel).grid(row=0, column=2)

        # Center over Series View after widgets have a size.
        dlg.update_idletasks()
        parent_x = int(self.winfo_rootx())
        parent_y = int(self.winfo_rooty())
        parent_w = max(1, int(self.winfo_width()))
        parent_h = max(1, int(self.winfo_height()))
        dlg_w = max(dlg.winfo_reqwidth(), dlg.winfo_width())
        dlg_h = max(dlg.winfo_reqheight(), dlg.winfo_height())
        x = parent_x + max(0, (parent_w - dlg_w) // 2)
        y = parent_y + max(0, (parent_h - dlg_h) // 2)
        dlg.geometry(f"+{x}+{y}")

        dlg.wait_window()

        profile = choice["profile"]
        if profile is None:
            return

        paths: list[Path] | None = None
        folder: Path | None = None
        filetypes = [
            (_("Segment volumes"), "*.nii *.nii.gz *.nrrd *.seg.nrrd"),
            (_("NIfTI"), "*.nii *.nii.gz"),
            (_("NRRD"), "*.nrrd *.seg.nrrd"),
            (_("All files"), "*.*"),
        ]
        if profile == ImportProfile.FOLDER_TS:
            folder_str = filedialog.askdirectory(parent=self, title=_("TotalSegmentator / mask folder"))
            if not folder_str:
                return
            folder = Path(folder_str)
        else:
            selected = filedialog.askopenfilenames(parent=self, title=_("Import Segments"), filetypes=filetypes)
            if not selected:
                return
            paths = [Path(p) for p in selected]

        try:
            result = self._workspace.import_annotate_segments(
                session,
                paths=paths,
                folder=folder,
                profile=profile,
            )
        except Exception as exc:
            logger.exception("Segment import failed")
            messagebox.showerror(title=_("Import Segments"), message=str(exc), parent=self)
            return

        for entry in result.entries:
            key = f"user:{entry.label_id}"
            self.image_viewer._active_segmentation_names.add(key)
            self.image_viewer.remember_view_latch(key)
            self._latch_user_label_overlay(key)

        self._refresh_paint_target_options()
        self._push_merged_segmentation_overlays()
        self._schedule_annotate_save()

        names = ", ".join(e.name for e in result.entries[:5])
        if len(result.entries) > 5:
            names += "…"
        status = _("Imported") + f" {len(result.entries)} " + _("segment(s)")
        if names:
            status += f": {names}"
        if result.resampled:
            status += " (" + _("resampled") + ")"
        if result.warnings:
            status += " — " + result.warnings[0]
        self.update_status(status)

    def _on_annotate_mode_changed(self, mode: str) -> None:
        if mode == "annotate":
            self._ensure_annotate_session()
            self._refresh_paint_target_options()
            self._recontour_visible_user_labels_current_slice()
            self._push_merged_segmentation_overlays()
        else:
            self._flush_annotate_save(update_ledger=True)

    def _on_annotate_target_changed(self, key: str | None) -> None:
        # Annotate draws only the paint target — refresh so previous segments disappear.
        if hasattr(self, "image_viewer") and self.image_viewer.get_annotate_mode() == "annotate":
            self._recontour_visible_user_labels_current_slice()
            self._push_merged_segmentation_overlays()

    def _on_annotate_requires_target(self) -> None:
        messagebox.showinfo(
            title=_("Annotate"),
            message=_("Create or select a segment before painting."),
            parent=self,
        )

    def _on_annotate_stroke(self, target_key: str, cy: int, cx: int, radius: int, tool: str) -> None:
        session = self._ensure_annotate_session()
        if session is None:
            return
        frame_index = self.image_viewer.current_image_index
        slice_index = self._anatomical_slice_for_viewer_frame(frame_index)
        if slice_index is None:
            return
        if target_key.startswith("user:"):
            try:
                lid = int(target_key.split(":", 1)[1])
            except ValueError:
                return
            volume = session.labels
            value = 0 if tool == "erase" else lid
            kind = "user"
            structure = None
        elif target_key.startswith("ts:"):
            name = target_key.split(":", 1)[1]
            source = self._structure_mask_by_name.get(name)
            if source is None:
                try:
                    source = load_primary_segment_mask(self._seg_dir(), name)
                    self._structure_mask_by_name[name] = source
                except Exception:
                    logger.exception("Cannot load TS mask for edit target %s", name)
                    return
            volume = self._workspace.ensure_ts_edit_volume(session, name, source_mask=source)
            self._structure_mask_by_name[name] = volume
            value = 0 if tool == "erase" else 1
            kind = "ts_edit"
            structure = name
        else:
            return

        if self._stroke_before is None:
            self._stroke_kind = kind
            self._stroke_structure = structure
            self._stroke_slice = slice_index

        self._stroke_before = self._workspace.apply_annotate_stroke(
            session,
            volume=volume,
            slice_index=slice_index,
            cy=cy,
            cx=cx,
            radius=radius,
            value=value,
            stroke_before=self._stroke_before,
        )
        # Throttle full-slice recontour + frame redraw while the mouse is moving.
        self._schedule_annotate_recontour(target_key, slice_index)

    def _on_annotate_stroke_end(self) -> None:
        session = self._annotate_session
        if session is None or self._stroke_before is None:
            return
        self._workspace.finish_annotate_stroke(
            session,
            kind=self._stroke_kind or "user",
            structure_name=self._stroke_structure,
            slice_index=int(self._stroke_slice or 0),
            before_slice=self._stroke_before,
        )
        pending = self._pending_annotate_recontour
        self._stroke_before = None
        self._stroke_kind = None
        self._stroke_structure = None
        self._stroke_slice = None
        self._flush_annotate_recontour()
        if pending is None and hasattr(self, "image_viewer"):
            # Ensure final contour even if the last motion already flushed.
            paint = self.image_viewer.get_paint_target_key()
            frame_index = self.image_viewer.current_image_index
            slice_index = self._anatomical_slice_for_viewer_frame(frame_index)
            if paint is not None and slice_index is not None:
                self._recontour_after_paint(paint, slice_index)
        self._schedule_annotate_save()

    def _schedule_annotate_recontour(self, target_key: str, slice_index: int) -> None:
        self._pending_annotate_recontour = (target_key, slice_index)
        if self._annotate_recontour_after_id is not None:
            return
        self._annotate_recontour_after_id = self.after(50, self._flush_annotate_recontour)

    def _flush_annotate_recontour(self) -> None:
        if self._annotate_recontour_after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._annotate_recontour_after_id)
            self._annotate_recontour_after_id = None
        pending = self._pending_annotate_recontour
        self._pending_annotate_recontour = None
        if pending is None:
            return
        target_key, slice_index = pending
        self._recontour_after_paint(target_key, slice_index)

    def _recontour_after_paint(self, target_key: str, slice_index: int) -> None:
        session = self._annotate_session
        if session is None:
            return
        if target_key.startswith("user:"):
            try:
                lid = int(target_key.split(":", 1)[1])
            except ValueError:
                return
            entry = session.label_map.get(lid)
            if entry is None:
                return
            plane = (session.labels[slice_index] == lid).astype(np.uint8)
            segs = mask_slice_to_segmentations(
                plane,
                structure_name=entry.name,
                color_bgr=entry.color_bgr,
                label_id=lid,
                label_name=entry.name,
                source="user",
                editable=True,
                filled=False,
                # Live brush: skip Gaussian smooth (expensive on CT slices).
                smooth_sigma=0.0,
                contour_smooth_window=0,
            )
            cache = self._user_label_overlays.setdefault(target_key, {})
            cache[slice_index] = segs
        elif target_key.startswith("ts:"):
            name = target_key.split(":", 1)[1]
            mask = self._structure_mask_by_name.get(name)
            if mask is None:
                return
            color = color_bgr_for_structure(name)
            segs = mask_slice_to_segmentations(
                mask[slice_index],
                structure_name=name,
                color_bgr=color,
                source="edited",
                editable=True,
                filled=False,
                smooth_sigma=0.0,
                contour_smooth_window=0,
            )
            cache = self._structure_overlay_by_name.setdefault(name, {})
            cache[slice_index] = segs
        self._push_merged_segmentation_overlays()

    def _recontour_visible_user_labels_current_slice(self) -> None:
        """Recontour user-label overlays that are currently visible (Annotate: paint target only)."""
        session = self._annotate_session
        if session is None or not hasattr(self, "image_viewer"):
            return
        frame_index = self.image_viewer.current_image_index
        slice_index = self._anatomical_slice_for_viewer_frame(frame_index)
        if slice_index is None:
            return
        for key in self._visible_segmentation_keys():
            if key.startswith("user:"):
                self._recontour_after_paint(key, slice_index)

    def _on_annotate_undo(self) -> None:
        session = self._annotate_session
        if session is None:
            return
        if not self._workspace.undo_annotate_stroke(session):
            return
        visible = self._visible_segmentation_keys()
        # Refresh structure masks from edits for visible TS targets only.
        for name, edited in session.ts_edits.items():
            self._structure_mask_by_name[name] = edited
            if name in visible and name in self._structure_overlay_by_name:
                frame_index = self.image_viewer.current_image_index
                slice_index = self._anatomical_slice_for_viewer_frame(frame_index)
                if slice_index is not None:
                    self._recontour_after_paint(f"ts:{name}", slice_index)
        frame_index = self.image_viewer.current_image_index
        slice_index = self._anatomical_slice_for_viewer_frame(frame_index)
        if slice_index is not None:
            for key in visible:
                if key.startswith("user:"):
                    self._recontour_after_paint(key, slice_index)
        self._schedule_annotate_save()

    def _on_annotate_new_label(self) -> None:
        session = self._ensure_annotate_session()
        if session is None:
            messagebox.showinfo(
                title=_("Annotate"),
                message=_("Could not create annotation geometry for this series."),
                parent=self,
            )
            return

        result = show_new_segment_dialog(self, session)
        if not result.applied or not result.name:
            return
        try:
            entry = self._workspace.add_annotate_user_label(
                session,
                result.name,
                normative_organ=result.normative_organ,
            )
        except ValueError:
            messagebox.showwarning(
                title=_("New Segment"),
                message=_("A segment with this name already exists"),
                parent=self,
            )
            return
        key = f"user:{entry.label_id}"
        # Keep the new chip in the shared View latch set so it remains listed next to TS.
        self.image_viewer._active_segmentation_names.add(key)
        self.image_viewer.remember_view_latch(key)
        self._refresh_paint_target_options()
        self.image_viewer._select_annotate_segment(key)
        self.image_viewer.reveal_segmentation_button(key)
        self._schedule_annotate_save()
        self.update_status(_("Created segment") + f": {entry.name}")

    def _schedule_annotate_save(self) -> None:
        """Debounce NIfTI write; ledger updates wait until leave-annotate / close."""
        if self._annotate_save_after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._annotate_save_after_id)
        # 2s debounce: CT label volumes are large; mouse-up should not block painting.
        self._annotate_save_after_id = self.after(
            2000, lambda: self._flush_annotate_save(update_ledger=False)
        )

    def _flush_annotate_save(self, *, update_ledger: bool = True) -> None:
        if self._annotate_save_after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._annotate_save_after_id)
            self._annotate_save_after_id = None
        self._workspace.flush_annotate_session(
            self._annotate_session,
            update_ledger=update_ledger,
        )

    def clear_ts_cache_button_clicked(self) -> None:

        if self._ds is None or Modality.from_code(getattr(self._ds, "Modality", None)) not in {
            Modality.CT,
            Modality.MR,
        }:
            return
        if not self._clear_ts_cache_button_visible():
            return

        summary, has_annotations = self._workspace.tseg_cache_info()
        size_mb = summary.size_bytes / (1024 * 1024) if summary.exists else 0.0
        size_text = f"{size_mb:.1f} MB" if size_mb >= 0.1 else _("< 0.1 MB")
        file_count = summary.file_count if summary.exists else 0

        cache_message = (
            _("Delete analysis cache for this series?")
            + "\n\n"
            + _("Removes geometry, segmentation masks, contrast analysis, and face mask under")
            + f" {TSEG_CACHE_DIRNAME}/ ({size_text}, {file_count} "
            + _("files")
            + ").\n\n"
            + _("DICOM images and series description are not changed.")
            + "\n\n"
            + _("Harmonize analysis can be re-run after clearing the cache.")
        )
        if has_annotations:
            cache_message += (
                "\n\n"
                + _("ROI annotations were found.")
                + "\n"
                + _("Yes = clear cache and annotations")
                + "\n"
                + _("No = clear Harmonize cache only (keep annotations)")
                + "\n"
                + _("Cancel = abort")
            )
        anon_uid = self._anon_series_uid()
        if anon_uid is not None and self._controller.series_has_face_blur(anon_uid):
            cache_message += "\n\n" + _(
                "Face blur has already been applied; blurred pixels and Blur Face status are unchanged."
            )

        if has_annotations:
            confirmed = messagebox.askyesnocancel(
                title=_("Clear Analysis Cache"),
                message=cache_message,
                parent=self,
                default="no",
            )
            if confirmed is None:
                return
            also_clear_annotations = bool(confirmed)
        else:
            confirmed = messagebox.askyesno(
                title=_("Clear Analysis Cache"),
                message=cache_message,
                parent=self,
                default="no",
            )
            if not confirmed:
                return
            also_clear_annotations = True

        logger.info(
            "Clearing TS cache for %s also_annotations=%s",
            self._series_path,
            also_clear_annotations,
        )
        self._flush_annotate_save()
        self._annotate_session = None
        self._user_label_overlays.clear()
        self._workspace.clear_series_tseg_cache(
            anon_series_uid=anon_uid,
            also_clear_annotations=also_clear_annotations,
        )
        self._series_geometry = None
        self._face_blur_eligibility_cache = None
        self._face_blur_eligibility_geometry = None
        self.after_idle(self._finish_clear_ts_cache)

    def _finish_clear_ts_cache(self) -> None:
        if not self._widget_alive():
            return
        self._invalidate_structure_overlays()
        self._user_label_overlays.clear()
        self._annotate_session = None
        self._refresh_analysis_cache_ui()
        self._sync_annotate_availability()
        self.update_status(_("Analysis cache cleared"))
        self._refresh_series_processing_status()

    def blur_face_button_clicked(self) -> None:
        anon_uid = self._anon_series_uid()
        if anon_uid is not None and self._controller.series_has_face_blur(anon_uid):
            messagebox.showinfo(
                title=_("Blur Face"),
                message=face_blur_gate_message(FaceBlurGateReason.ALREADY_APPLIED),
                parent=self,
            )
            return
        if not self._series_interaction_allowed() or not self._blur_face_toolbar_visible():
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
        index_parent = find_dataset_view_parent(self) or self._parent

        logger.info(
            "Series View: opening face blur review for %s (gate=%s)",
            self._series_path,
            eligibility.reason.name,
        )
        self._on_cancel()
        show_face_blur_review_dialog(
            index_parent,
            anon_model=self._controller.anonymizer.model,
            series_path=self._series_path,
            blur_mode=blur_mode,
        )

    def _persist_whitelist_if_changed(self) -> None:
        if self._ds is None or self._ds.Modality is None:
            if self._whitelist_changed or self._whitelist_match_changed:
                logger.error("CRITICAL: Modality not found in dataset")
            return
        project_dir = self._controller.model.storage_dir

        if self._whitelist_changed:
            whitelist_set = self.get_whitelist_set()
            if whitelist_set:
                try:
                    whitelist_filepath = save_project_whitelist(project_dir, self._ds.Modality, whitelist_set)
                    self._whitelist_changed = False
                    self._log_whitelist_trace("save", delta=f"path={whitelist_filepath}")
                except Exception as e:
                    logger.error(f"Error saving whitelist: {e}")

        if self._whitelist_match_changed:
            try:
                settings = self._whitelist_match_settings_from_ui()
                self._whitelist_match_settings = settings
                options_path = save_modality_whitelist_match_settings(project_dir, self._ds.Modality, settings)
                self._whitelist_match_changed = False
                self._log_whitelist_trace(
                    "match_save",
                    delta=f"path={options_path} mode={describe_match_settings(settings)}",
                )
            except Exception as e:
                logger.error(f"Error saving whitelist match settings: {e}")

    def save_series_button_clicked(self):
        if self._ds is None:
            logger.error("CRITICAL: No frames or dataset to save")
            return
        pixel_dirty = bool(self._pixel_phi_dirty)
        exclude_dirty = self._exclude_areas_dirty()
        if not pixel_dirty and not exclude_dirty:
            return
        if pixel_dirty and self._frames is None:
            logger.error("CRITICAL: No frames or dataset to save")
            return

        whitelist_items: list[str] | None = None
        whitelist_match: OcrWhitelistMatchSettings | None = None
        if self._whitelist_changed:
            whitelist_set = self.get_whitelist_set()
            if whitelist_set:
                whitelist_items = list(whitelist_set)
        if self._whitelist_match_changed:
            whitelist_match = self._whitelist_match_settings_from_ui()
            self._whitelist_match_settings = whitelist_match

        texts_by_frame: dict[int, list[str]] = {}
        if pixel_dirty and hasattr(self, "image_viewer"):
            texts_by_frame = dict(collect_series_view_embedded_phi_texts(self.image_viewer))
            for frame_index, removed in self._removed_pixel_phi_by_frame.items():
                merged = list(texts_by_frame.get(frame_index, []))
                for label in removed:
                    if label not in merged:
                        merged.append(label)
                if merged:
                    texts_by_frame[frame_index] = merged

        result = self._workspace.save_series_view_edits(
            SeriesViewSaveRequest(
                series_path=self._series_path,
                frames=self._frames,
                dataset=self._ds,
                slice_paths=self._slice_paths,
                project_dir=self._controller.model.storage_dir,
                anon_model=self._controller.anonymizer.model,
                pixel_dirty=pixel_dirty,
                exclude_dirty=exclude_dirty,
                exclude_rects_normalized=self._all_active_exclude_normalized(),
                whitelist_items=whitelist_items,
                whitelist_match_settings=whitelist_match,
                texts_by_frame=texts_by_frame,
                ocr_transcript_by_frame=self._ocr_transcript_by_frame,
            )
        )
        if not result.ok:
            messagebox.showerror(
                title=_("Save Changes Error"),
                message=result.error_message or _("Failed to save changes to series frames"),
                parent=self,
            )
            self.update_status(_("Could not save changes"))
            return

        if whitelist_items is not None:
            self._whitelist_changed = False
        if whitelist_match is not None:
            self._whitelist_match_changed = False
        self._saved_exclude_fingerprint = result.saved_exclude_fingerprint
        if result.ocr_sr_note:
            self._ocr_transcript_by_frame.clear()

        if result.should_close:
            self._removed_pixel_phi_by_frame.clear()
            self._pixel_phi_dirty = False
            self._refresh_save_button()
            self._refresh_series_processing_status()
            self.update_status(_("Changes saved") + result.exclude_note + result.ocr_sr_note)
            self._on_cancel()
            return

        self._refresh_save_button()
        self.update_status(_("Changes saved") + result.exclude_note)

    def whitelist_defaults_button_clicked(self):
        self.clear_whitelist()
        self.load_whitelist_defaults()
        self._whitelist_changed = True
        self._whitelist_match_settings = default_whitelist_match_settings()
        self._whitelist_match_changed = True
        self._apply_whitelist_match_settings_to_ui()
        self._log_whitelist_trace("match_mode", delta=describe_match_settings(self._whitelist_match_settings))

    def load_whitelist_defaults(self):
        # TODO: whitelist load error message to user
        if self._ds is None:
            logger.error("CRITICAL: self._ds is None")
            return
        if self._ds.Modality is None:
            logger.error("CRITICAL: Modality not found in dataset")
            return

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
        self._log_whitelist_trace("load_defaults")

    def _bind_slice_navigation_keys(self) -> None:
        """Forward arrow/page keys to ImageViewer unless focus is in an editable field."""
        if self.single_frame or self._frames is None or self._frames.shape[0] <= 1:
            return
        bindings = (
            ("<Left>", "prev_image"),
            ("<Right>", "next_image"),
            ("<Up>", "change_image_up"),
            ("<Down>", "change_image_down"),
            ("<Prior>", "change_image_prior"),
            ("<Next>", "change_image_next"),
            ("<Home>", "change_image_home"),
            ("<End>", "change_image_end"),
        )
        for sequence, method_name in bindings:
            self.bind(sequence, lambda event, name=method_name: self._on_slice_navigation_key(event, name))

    def _focus_is_text_input(self) -> bool:
        focused = self.focus_get()
        if focused is None:
            return False
        cls = focused.winfo_class()
        if cls in {"Entry", "TEntry", "Listbox", "Text", "TCombobox"}:
            return True
        return isinstance(focused, (ctk.CTkEntry, ctk.CTkComboBox, ctk.CTkTextbox))

    def _on_slice_navigation_key(self, event, method_name: str):
        if self._focus_is_text_input():
            return
        viewer = getattr(self, "image_viewer", None)
        if viewer is None:
            return
        handler = getattr(viewer, method_name, None)
        if handler is None:
            return
        handler(event)
        return "break"

    def _focus_image_viewer_for_keys(self) -> None:
        if not self._widget_alive():
            return
        viewer = getattr(self, "image_viewer", None)
        if viewer is None:
            return
        with contextlib.suppress(tk.TclError):
            viewer.canvas.focus_set()

    def _escape_keypress(self, event):
        logger.info("_escape_pressed")
        self._on_cancel()

    def _trace_load(self, step: str, **details: object) -> None:
        """Structured INFO trace for Series View open / startup sequencing."""
        parts = [f"step={step}", f"series={self._series_path.name}"]
        parts.extend(f"{key}={value}" for key, value in details.items())
        logger.info("SeriesView load: %s", " ".join(parts))

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
            collect_garbage_safe(generations=2)
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
        self._removed_pixel_phi_by_frame.clear()
        self._pixel_phi_dirty = False

    def _on_cancel(self):
        logger.info("_on_cancel")
        if getattr(self, "_closing", False):
            return
        self._closing = True
        if self._annotate_recontour_after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._annotate_recontour_after_id)
            self._annotate_recontour_after_id = None
        self._pending_annotate_recontour = None
        self._flush_annotate_save(update_ledger=True)
        self._structure_contour_generation += 1
        self._clear_structure_latch_state()
        if self._structure_contour_poll_after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._structure_contour_poll_after_id)
            self._structure_contour_poll_after_id = None
        if not self._ocr_work_state.done:
            self._ocr_work_state.request_cancel()
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
        self._persist_whitelist_if_changed()

        self._release_all_viewer_resources()
        self._release_series_data()

        with contextlib.suppress(tk.TclError):
            self.grab_release()

        parent = self._parent
        return_to_dataset_view(self)
        self.destroy()
        self._schedule_post_close_gc(parent, rss_before)
