"""Modal face blur preview and review dialog."""

from __future__ import annotations

import contextlib
import copy
import logging
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk
import numpy as np
from pydicom import Dataset

from anonymizer.controller.ai.blur_face import (
    FaceBlurMode,
    FaceBlurPreviewResult,
    SeriesVolumeContext,
    apply_series_face_blur_metadata,
    mask_slice_segmentations,
    preview_blurred_slice_frames,
    preview_face_blur,
)
from anonymizer.controller.ai.remove_pixel_phi import LayerType
from anonymizer.controller.ai.tseg.dicom_geometry import (
    SeriesGeometryResult,
    ensure_series_geometry,
    load_geometry_cache,
)
from anonymizer.controller.runner import Algorithm
from anonymizer.controller.series_io import load_series_frames, save_series_frames
from anonymizer.controller.work_state import WorkState
from anonymizer.model.anonymizer import AnonymizerModel
from anonymizer.utils.translate import _
from anonymizer.view.ai.blur_face_results import (
    FACE_MASK_OVERLAY_ALPHA,
    FACE_MASK_OVERLAY_COLOR,
    face_blur_mode_display_label,
    face_review_wl_ww,
    format_face_blur_progress_status,
    format_face_blur_qa_summary,
    proposed_face_blur_companion_label,
)
from anonymizer.view.ai.harmonize_results import HarmonizeResultsView
from anonymizer.view.common.app_window import AppCTkToplevel
from anonymizer.view.common.ctk_safe import teardown_ctk_toplevel
from anonymizer.view.common.job_poller import LOAD_POLL_MS, STAGE_POLL_MS, start_background_job
from anonymizer.view.common.navigation import return_to_phi_index
from anonymizer.view.series.image import ImageViewer

logger = logging.getLogger(__name__)


class FaceBlurLoadError(Exception):
    """Raised when DICOM series pixels cannot be loaded for face blur review."""


@dataclass(frozen=True)
class FaceBlurReviewOutcome:
    saved: bool
    cancelled: bool


class FaceBlurReviewDialog(AppCTkToplevel):
    BLUR_POLL_MS = STAGE_POLL_MS
    LOAD_POLL_MS = LOAD_POLL_MS
    PAD = 10
    BUTTON_WIDTH = 100
    DEFAULT_WIDTH = 1200
    DEFAULT_HEIGHT = 720
    LOADING_SHELL_WIDTH = 420
    LOADING_SHELL_HEIGHT = 72
    LOADING_SHELL_PAD = 12
    LOAD_PROGRESS_PULSE_MS = 180

    def __init__(
        self,
        parent: tk.Misc,
        *,
        anon_model: AnonymizerModel,
        series_path: Path,
        blur_mode: FaceBlurMode,
    ) -> None:
        super().__init__(master=parent)

        self._parent = parent
        self._anon_model = anon_model
        self._series_path = series_path
        self._blur_mode = blur_mode
        self._outcome = FaceBlurReviewOutcome(saved=False, cancelled=True)
        self._closing = False
        self._destroyed = False

        self._ds: Dataset | None = None
        self._slice_frames: np.ndarray | None = None
        self._slice_paths: tuple[Path, ...] = ()
        self._series_geometry: SeriesGeometryResult | None = None
        self._preview: FaceBlurPreviewResult | None = None

        self._loading = True
        self._blur_running = False
        self._load_work_state = WorkState()
        self._blur_work_state = WorkState()
        self._load_progress_after_id: str | None = None
        self._load_progress_value = 0.0
        self._loading_shell: ctk.CTkFrame | None = None
        self._load_progress: ctk.CTkProgressBar | None = None

        self.title(_("Blur Face"))
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Escape>", self._escape_keypress)

        self.withdraw()
        self._show_loading_shell()
        self.deiconify()
        self.wait_visibility()
        self.grab_set()
        self.lift()

        self._load_work_state.prepare_job()

        def _load_worker() -> None:
            self._run_load_job()

        start_background_job(
            self,
            work_state=self._load_work_state,
            algorithm=Algorithm.FACE_BLUR,
            worker_target=_load_worker,
            on_done=self._on_load_job_done,
            poll_ms=self.LOAD_POLL_MS,
        )

    def _widget_alive(self) -> bool:
        if self._destroyed or self._closing:
            return False
        with contextlib.suppress(tk.TclError):
            return bool(self.winfo_exists())
        return False

    def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        self._stop_load_progress_pulse()
        self._load_work_state.request_cancel()
        self._blur_work_state.request_cancel()
        super().destroy()

    def _progress_bar_width(self) -> int:
        return self.LOADING_SHELL_WIDTH - (2 * self.LOADING_SHELL_PAD)

    def _show_loading_shell(self) -> None:
        width = self.LOADING_SHELL_WIDTH
        height = self.LOADING_SHELL_HEIGHT
        self.geometry(f"{width}x{height}")
        self.resizable(False, False)

        self._loading_shell = ctk.CTkFrame(self, fg_color="transparent")
        pad = self.LOADING_SHELL_PAD
        self._loading_shell.pack(fill="both", expand=True, padx=pad, pady=pad)

        ctk.CTkLabel(
            self._loading_shell,
            text=f"{_('Loading series')}…  {self._series_path.name}",
            anchor="w",
        ).pack(fill="x", pady=(0, 8))

        self._load_progress = ctk.CTkProgressBar(
            self._loading_shell,
            width=self._progress_bar_width(),
        )
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

    @staticmethod
    def _load_series_slices(
        series_path: Path,
    ) -> tuple[Dataset, np.ndarray, tuple[Path, ...], SeriesGeometryResult | None]:
        loaded = load_series_frames(series_path)
        ds, series_frames, slice_paths = loaded.metadata, loaded.frames, loaded.slice_paths
        if ds is None or series_frames is None:
            raise FaceBlurLoadError(f"Error loading frames from {series_path}")

        series_geometry: SeriesGeometryResult | None = None
        if getattr(ds, "Modality", None) == "CT":
            series_geometry = load_geometry_cache(series_path)
        return ds, series_frames, slice_paths, series_geometry

    def _run_load_job(self) -> None:
        try:
            payload = self._load_series_slices(self._series_path)
            self._load_work_state.finish(payload)
        except Exception as exc:
            logger.exception("Face blur review load failed for %s", self._series_path)
            self._load_work_state.fail(str(exc))

    def _on_load_job_done(self, _algorithm: Algorithm | None, work_state: WorkState) -> None:
        if not self._widget_alive():
            return
        if work_state.error:
            messagebox.showerror(
                title=_("Blur Face"),
                message=_("Could not load this series.") + f"\n\n{work_state.error}",
                parent=self,
            )
            self._close(cancelled=True)
            return
        payload = work_state.result
        if not isinstance(payload, tuple) or len(payload) != 4:
            messagebox.showerror(
                title=_("Blur Face"),
                message=_("Could not load this series."),
                parent=self,
            )
            self._close(cancelled=True)
            return
        ds, slice_frames, slice_paths, geometry = payload
        self._finish_load(ds, slice_frames, slice_paths, geometry)

    def _finish_load(
        self,
        ds: Dataset,
        slice_frames: np.ndarray,
        slice_paths: tuple[Path, ...],
        geometry: SeriesGeometryResult | None,
    ) -> None:
        self._loading = False
        self._ds = ds
        self._slice_frames = slice_frames
        self._slice_paths = slice_paths
        self._series_geometry = geometry

        self.withdraw()
        self._stop_load_progress_pulse()
        if self._loading_shell is not None:
            with contextlib.suppress(tk.TclError):
                self._loading_shell.destroy()
            self._loading_shell = None
            self._load_progress = None

        self.resizable(False, False)
        self.geometry(f"{self.DEFAULT_WIDTH}x{self.DEFAULT_HEIGHT}")
        self._build_ui()
        self._position_near_parent(width=self.DEFAULT_WIDTH, height=self.DEFAULT_HEIGHT)
        self._apply_fixed_viewer_sizing()
        self.deiconify()
        self.lift()
        self.after_idle(self._start_blur_worker)

    def _position_near_parent(self, *, width: int | None = None, height: int | None = None) -> None:
        self.update_idletasks()
        width = width or self.winfo_width() or self.DEFAULT_WIDTH
        height = height or self.winfo_height() or self.DEFAULT_HEIGHT
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

    def _phi_header(self):
        resolve = getattr(self._anon_model, "get_study_phi_header_by_anon_study_uid", None)
        if resolve is None or self._ds is None:
            return None
        return resolve(str(self._ds.StudyInstanceUID))

    def _build_ui(self) -> None:
        assert self._ds is not None and self._slice_frames is not None

        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=0)
        self.grid_columnconfigure(0, weight=1)

        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.grid(row=0, column=0, padx=self.PAD, pady=(self.PAD, 0), sticky="ew")
        header_frame.grid_columnconfigure(0, weight=1)

        study_description = str(self._ds.get("StudyDescription", "") or "").strip()
        series_description = str(self._ds.get("SeriesDescription", "") or "").strip()
        phi_header = self._phi_header()

        ctk.CTkLabel(
            header_frame,
            text=HarmonizeResultsView.format_study_header(study_description, phi_header=phi_header),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(
            header_frame,
            text=HarmonizeResultsView.format_series_description_header(
                ds=self._ds,
                current_description=series_description,
            ),
            anchor="w",
        ).grid(row=1, column=0, sticky="ew")
        ctk.CTkLabel(
            header_frame,
            text=HarmonizeResultsView.format_study_context_line(
                phi_header=phi_header,
                ds=self._ds if phi_header is None else None,
            ),
            anchor="w",
        ).grid(row=2, column=0, sticky="ew")

        self._viewer_frame = ctk.CTkFrame(self)
        self._viewer_frame.grid(row=1, column=0, padx=self.PAD, pady=self.PAD, sticky="nsew")
        self._viewer_frame.grid_rowconfigure(0, weight=1)
        self._viewer_frame.grid_columnconfigure(0, weight=1)

        review_wl, review_ww = face_review_wl_ww(self._ds)
        slice_stack = self._slice_frames.copy()
        self.image_viewer = ImageViewer(
            self._viewer_frame,
            slice_stack,
            review_wl,
            review_ww,
            show_data_panel=False,
            show_playback_controls=False,
            enable_interactive_editing=False,
        )
        self.image_viewer.grid(row=0, column=0, sticky="nsew")
        self.image_viewer.segmentation_overlay_color = FACE_MASK_OVERLAY_COLOR
        self.image_viewer.segmentation_overlay_alpha = FACE_MASK_OVERLAY_ALPHA
        self.image_viewer.active_layers.discard(LayerType.TEXT)
        self.image_viewer.active_layers.discard(LayerType.USER_RECT)
        self.image_viewer.active_layers.discard(LayerType.SEGMENTATIONS)
        self.image_viewer.attach_companion_stack(
            slice_stack.copy(),
            primary_label=_("Current"),
            companion_label=proposed_face_blur_companion_label(self._blur_mode),
        )
        self.image_viewer.set_wlww_sync(review_wl, review_ww)
        self.image_viewer.set_interaction_enabled(True)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, padx=self.PAD, pady=(0, self.PAD), sticky="ew")
        footer.grid_columnconfigure(1, weight=1)

        self._status_label = ctk.CTkLabel(
            footer,
            text=_("Preparing face blur preview") + "…",
            anchor="w",
            justify="left",
        )
        self._status_label.grid(row=0, column=0, columnspan=5, sticky="ew", pady=(0, self.PAD))

        self._progressbar = ctk.CTkProgressBar(footer, width=self._progress_bar_width())
        self._progressbar.grid(row=1, column=0, sticky="w", pady=(0, self.PAD))
        self._progressbar.set(0)

        ctk.CTkLabel(
            footer,
            text=face_blur_mode_display_label(self._blur_mode),
            anchor="w",
        ).grid(row=1, column=2, padx=(self.PAD, self.PAD), sticky="e")

        self._cancel_button = ctk.CTkButton(
            footer,
            width=self.BUTTON_WIDTH,
            text=_("Cancel"),
            command=self._on_cancel,
        )
        self._cancel_button.grid(row=1, column=3, padx=(0, self.PAD), sticky="e")

        self._save_button = ctk.CTkButton(
            footer,
            width=self.BUTTON_WIDTH,
            text=_("Save"),
            command=self._save_button_clicked,
            state="disabled",
        )
        self._save_button.grid(row=1, column=4, sticky="e")

    def _update_status(self, message: str) -> None:
        if hasattr(self, "_status_label"):
            self._status_label.configure(text=message)

    def _ensure_series_geometry(self) -> SeriesGeometryResult | None:
        self._series_geometry = ensure_series_geometry(
            self._series_path,
            ds=self._ds,
            cached=self._series_geometry,
        )
        return self._series_geometry

    def _start_blur_worker(self) -> None:
        if not self._widget_alive() or self._slice_frames is None or self._ds is None:
            return
        self._blur_running = True
        self._blur_work_state.prepare_job()
        self._update_status(_("Preparing face blur preview") + "…")
        self._progressbar.set(0)
        self.after_idle(lambda: self._launch_blur_worker(self._blur_mode))

    def _launch_blur_worker(self, blur_mode: FaceBlurMode) -> None:
        if not self._blur_running or not self._widget_alive():
            return
        if self._slice_frames is None or self._ds is None:
            self._blur_running = False
            return

        geometry = self._ensure_series_geometry()
        volume_context = SeriesVolumeContext(
            reference_ds=copy.deepcopy(self._ds),
            slice_frames=self._slice_frames.copy(),
            slice_paths=self._slice_paths,
            slice_spacing_mm=geometry.slice_spacing_mm if geometry is not None else None,
        )

        def _blur_worker() -> None:
            self._run_blur_job(blur_mode, volume_context)

        start_background_job(
            self,
            work_state=self._blur_work_state,
            algorithm=Algorithm.FACE_BLUR,
            worker_target=_blur_worker,
            on_tick=self._on_blur_job_tick,
            on_done=self._on_blur_job_done,
            poll_ms=self.BLUR_POLL_MS,
        )

    def _run_blur_job(self, blur_mode: FaceBlurMode, volume_context: SeriesVolumeContext) -> None:
        work_state = self._blur_work_state

        def on_progress(progress) -> None:
            if work_state.should_cancel():
                return
            fraction = getattr(progress, "fraction", 0.0)
            work_state.update_job_progress(
                status=format_face_blur_progress_status(progress),
                fraction=fraction,
                detail=progress,
            )

        try:
            preview = preview_face_blur(
                self._series_path,
                progress=on_progress,
                volume_context=volume_context,
                blur_mode=blur_mode,
            )
            if not work_state.should_cancel():
                work_state.finish(preview)
        except Exception as exc:
            logger.exception("Face blur preview worker failed for %s", self._series_path)
            work_state.fail(str(exc))

    def _on_blur_job_tick(self, work_state: WorkState) -> None:
        if not self._widget_alive() or not self._blur_running:
            return
        status, _done, fraction, _error, _result, _detail = work_state.read_job_ui()
        if status:
            self._update_status(status)
        self._progressbar.set(min(1.0, max(0.0, fraction)))

    def _on_blur_job_done(self, _algorithm: Algorithm | None, work_state: WorkState) -> None:
        if not self._widget_alive():
            return
        if not self._blur_running:
            return
        if work_state.error:
            self._blur_running = False
            messagebox.showerror(
                title=_("Blur Face"),
                message=str(work_state.error),
                parent=self,
            )
            self._close(cancelled=True)
            return
        preview = work_state.result
        if not isinstance(preview, FaceBlurPreviewResult):
            self._blur_running = False
            self._close(cancelled=True)
            return
        if preview.error is not None:
            self._blur_running = False
            messagebox.showerror(
                title=_("Blur Face"),
                message=preview.error,
                parent=self,
            )
            self._close(cancelled=True)
            return
        self._blur_running = False
        self.after_idle(lambda: self._show_blur_review(preview))

    def _show_blur_review(self, preview: FaceBlurPreviewResult) -> None:
        if self._slice_frames is None or self._ds is None:
            return

        self._preview = preview
        viewer = self.image_viewer
        if viewer.playing:
            viewer.toggle_play()

        blurred_frames = preview_blurred_slice_frames(
            preview,
            reference_ds=self._ds,
            frame_dtype=self._slice_frames.dtype,
        )

        segmentations_by_slice: dict[int, list] = {}
        for slice_index in range(preview.mask.shape[0]):
            segmentations = mask_slice_segmentations(preview.mask, slice_index)
            if segmentations:
                segmentations_by_slice[slice_index] = segmentations

        viewer.active_layers.add(LayerType.SEGMENTATIONS)
        if viewer._primary_label is not None:
            viewer._primary_label.configure(text=_("Current — face region (green)"))
        viewer.set_segmentation_overlays(segmentations_by_slice)
        viewer.update_companion_stack(blurred_frames)

        review_wl, review_ww = face_review_wl_ww(self._ds)
        viewer.set_wlww_sync(review_wl, review_ww)

        qa_summary = format_face_blur_qa_summary(
            preview.qa_stats,
            sigma_mm=preview.sigma_mm,
            slice_count=preview.slice_count,
            blur_mode=preview.blur_mode,
        )
        self._update_status(qa_summary + " — " + _("Review side-by-side, then Save to keep."))
        self._progressbar.set(1.0)
        self._save_button.configure(state="normal")

    def _apply_fixed_viewer_sizing(self) -> None:
        if not hasattr(self, "image_viewer") or self.image_viewer is None:
            return
        viewer = self.image_viewer
        viewer._resize_to_viewport_enabled = False
        self.update_idletasks()
        max_width, max_height = viewer._viewport_max_dimensions()
        if max_width <= 1 or max_height <= 1:
            return
        size = viewer._calculate_scaled_size(max_width, max_height, allow_upscale=False)
        viewer.current_size = size
        viewer.canvas.config(width=size[0], height=size[1])
        if viewer.companion_canvas is not None:
            viewer.companion_canvas.config(width=size[0], height=size[1])
        viewer._companion_cache.clear()
        viewer.load_and_display_image(viewer.current_image_index)

    def _save_button_clicked(self) -> None:
        preview = self._preview
        if preview is None or preview.error is not None or self._ds is None:
            return

        blurred_slices = preview_blurred_slice_frames(
            preview,
            reference_ds=self._ds,
            frame_dtype=self._slice_frames.dtype if self._slice_frames is not None else None,
        )
        if not save_series_frames(self._series_path, blurred_slices, self._ds):
            messagebox.showerror(
                title=_("Save Changes Error"),
                message=_("Failed to save changes to series frames"),
                parent=self,
            )
            return

        from anonymizer.controller.create_projections import invalidate_projection_cache

        invalidate_projection_cache(self._series_path)

        apply_series_face_blur_metadata(
            self._anon_model,
            str(self._ds.SeriesInstanceUID),
            preview.blur_mode.value,
        )
        logger.info(
            "Face blur review: saved for %s (slices=%d, qa=%s)",
            self._series_path,
            preview.slice_count,
            "PASS" if preview.qa_stats is None or preview.qa_stats.outside_clean else "FAIL",
        )
        self._close(saved=True)

    def _escape_keypress(self, _event) -> None:
        self._on_cancel()

    def _on_cancel(self) -> None:
        if self._blur_running:
            self._blur_work_state.request_cancel()
            return
        self._close(cancelled=True)

    def _close(self, *, saved: bool = False, cancelled: bool = False) -> None:
        if self._closing:
            return
        self._closing = True
        self._blur_running = False
        self._load_work_state.request_cancel()
        self._blur_work_state.request_cancel()
        self._stop_load_progress_pulse()
        self._outcome = FaceBlurReviewOutcome(saved=saved, cancelled=cancelled and not saved)
        if hasattr(self, "image_viewer"):
            with contextlib.suppress(tk.TclError):
                self.image_viewer.release_resources()
        parent = self._parent
        teardown_ctk_toplevel(self, parent=parent)
        return_to_phi_index(self._parent)

    def _cancel_after(self, attr: str) -> None:
        after_id = getattr(self, attr, None)
        if after_id is None:
            return
        with contextlib.suppress(tk.TclError):
            self.after_cancel(after_id)
        setattr(self, attr, None)

    def get_input(self) -> FaceBlurReviewOutcome:
        self.focus()
        self.master.wait_window(self)
        return self._outcome


def show_face_blur_review_dialog(
    parent: tk.Misc,
    *,
    anon_model: AnonymizerModel,
    series_path: Path,
    blur_mode: FaceBlurMode,
) -> FaceBlurReviewOutcome:
    """Open face blur review modally; returns whether the user saved or cancelled."""
    dialog = FaceBlurReviewDialog(
        parent,
        anon_model=anon_model,
        series_path=series_path,
        blur_mode=blur_mode,
    )
    return dialog.get_input()
