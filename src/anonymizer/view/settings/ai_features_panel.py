"""Clinical AI Features setup: enable tools and view simple readiness status."""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from tkinter import messagebox
from typing import Callable

import customtkinter as ctk

from anonymizer.controller.ai.remove_pixel_phi import download_ocr_models, remove_ocr_models
from anonymizer.controller.ai.tseg.runtime_status import (
    TsWeightKind,
    TsWeightState,
    TsWeightStatus,
    ai_feature_status_brain_structures,
    ai_feature_status_face_blur,
    ai_feature_status_harmonize,
    ai_feature_status_remove_pixel_phi,
    ai_feature_summary_brain_structures,
    ai_feature_summary_face_blur,
    ai_feature_summary_harmonize,
    ai_feature_summary_remove_pixel_phi,
    ai_feature_title_brain_structures,
    ai_feature_title_face_blur,
    ai_feature_title_harmonize,
    ai_feature_title_remove_pixel_phi,
    apply_face_license,
    brain_structures_has_models,
    brain_structures_needs_download,
    download_segmentation_model,
    face_blur_has_models,
    face_blur_needs_download,
    face_blur_needs_license,
    face_license_request_instructions,
    get_ai_session,
    get_runtime_status,
    get_stored_face_license,
    harmonize_has_models,
    harmonize_needs_download,
    refresh_weight_status,
    remove_pixel_phi_has_models,
    remove_pixel_phi_needs_download,
    remove_segmentation_model,
    set_ai_session,
    validate_face_license_format,
)
from anonymizer.utils.storage import (
    begin_model_download,
    end_model_download,
    get_model_download_progress,
    is_model_download_active,
)
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)

_FEATURE_LABELS = (
    (ai_feature_title_remove_pixel_phi(), "remove_pixel_phi"),
    (ai_feature_title_harmonize(), "enable_harmonize"),
    (ai_feature_title_face_blur(), "enable_face_blur"),
)

_FEATURE_SUMMARIES = {
    "remove_pixel_phi": ai_feature_summary_remove_pixel_phi,
    "enable_harmonize": ai_feature_summary_harmonize,
    "enable_face_blur": ai_feature_summary_face_blur,
}

_FEATURE_STATUS = {
    "remove_pixel_phi": ai_feature_status_remove_pixel_phi,
    "enable_harmonize": ai_feature_status_harmonize,
    "enable_face_blur": ai_feature_status_face_blur,
}

_FEATURE_PADY = (0, 10)
_DETAIL_PADX = (26, 0)
_TS_KIND_FEATURE_KEY = {
    TsWeightKind.ANATOMY: "enable_harmonize",
    TsWeightKind.FACE: "enable_face_blur",
    TsWeightKind.BRAIN_STRUCTURES: "enable_brain_structures",
}


class AiFeaturesPanel(ctk.CTkFrame):
    """Simple enable toggles with one-line status when a tool is selected."""

    POLL_MS = 200

    def __init__(
        self,
        master,
        *,
        on_flags_changed: Callable[[], None] | None = None,
        on_layout_changed: Callable[[], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._on_flags_changed = on_flags_changed
        self._on_layout_changed = on_layout_changed
        self._worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._download_thread: threading.Thread | None = None
        self._pending_ts_download: TsWeightKind | None = None
        self._license_thread: threading.Thread | None = None
        self._ocr_thread: threading.Thread | None = None
        self._license_validating = False
        self._poll_after_id: str | None = None
        self._destroyed = False
        self._license_var = tk.StringVar(value=get_stored_face_license())
        self._feature_vars: dict[str, tk.IntVar] = {}
        self._summary_labels: dict[str, ctk.CTkLabel] = {}
        self._status_labels: dict[str, ctk.CTkLabel] = {}
        self._action_frames: dict[str, ctk.CTkFrame] = {}
        self._progress_bars: dict[str, ctk.CTkProgressBar] = {}
        self._progress_details: dict[str, ctk.CTkLabel] = {}
        self._progress_indeterminate: dict[str, bool] = {}
        self._license_frame: ctk.CTkFrame | None = None
        self._license_entry: ctk.CTkEntry | None = None
        self._license_apply_button: ctk.CTkButton | None = None
        self._brain_structures_frame: ctk.CTkFrame | None = None
        self._brain_structures_status: ctk.CTkLabel | None = None
        self._brain_structures_actions: ctk.CTkFrame | None = None

        self.columnconfigure(0, weight=1)
        self._build_features()
        self.sync_from_runtime()
        self._schedule_poll()

    def sync_from_runtime(self) -> None:
        """Refresh status from on-disk models without altering session enable flags."""
        get_runtime_status(force_refresh=True)
        session = get_ai_session()
        for _label, key in _FEATURE_LABELS:
            self._feature_vars[key].set(1 if getattr(session, key) else 0)
        if "enable_brain_structures" in self._feature_vars:
            self._feature_vars["enable_brain_structures"].set(1 if session.enable_brain_structures else 0)
        self._refresh_status()

    def apply_session(self) -> None:
        set_ai_session(
            remove_pixel_phi=self._feature_vars["remove_pixel_phi"].get() == 1,
            enable_harmonize=self._feature_vars["enable_harmonize"].get() == 1,
            enable_face_blur=self._feature_vars["enable_face_blur"].get() == 1,
            enable_brain_structures=self._feature_vars.get("enable_brain_structures", tk.IntVar(value=0)).get()
            == 1,
        )

    def destroy(self) -> None:
        self._destroyed = True
        if self._poll_after_id is not None:
            self.after_cancel(self._poll_after_id)
        super().destroy()

    def _build_features(self) -> None:
        session = get_ai_session()
        for row, (label, key) in enumerate(_FEATURE_LABELS):
            block = ctk.CTkFrame(self, fg_color="transparent")
            block.grid(row=row, column=0, sticky="ew", pady=_FEATURE_PADY)
            block.columnconfigure(0, weight=1)

            var = tk.IntVar(value=1 if getattr(session, key) else 0)
            self._feature_vars[key] = var
            cb = ctk.CTkCheckBox(block, text=label, variable=var, command=self._on_toggle_changed)
            cb.grid(row=0, column=0, sticky="w")

            summary = ctk.CTkLabel(
                block,
                text="",
                anchor="w",
                justify="left",
                wraplength=500,
                text_color=("gray30", "gray75"),
            )
            summary.grid(row=1, column=0, sticky="w", padx=_DETAIL_PADX, pady=(2, 0))
            self._summary_labels[key] = summary

            status = ctk.CTkLabel(block, text="", anchor="w", justify="left", wraplength=500)
            status.grid(row=2, column=0, sticky="w", padx=_DETAIL_PADX, pady=(4, 0))
            self._status_labels[key] = status

            actions = ctk.CTkFrame(block, fg_color="transparent")
            self._action_frames[key] = actions

            if key == "enable_harmonize":
                self._brain_structures_frame = ctk.CTkFrame(block, fg_color="transparent")
                self._brain_structures_frame.grid(row=4, column=0, sticky="ew", padx=_DETAIL_PADX, pady=(6, 0))
                self._brain_structures_frame.columnconfigure(0, weight=1)
                brain_var = tk.IntVar(value=1 if session.enable_brain_structures else 0)
                self._feature_vars["enable_brain_structures"] = brain_var
                brain_cb = ctk.CTkCheckBox(
                    self._brain_structures_frame,
                    text=ai_feature_title_brain_structures(),
                    variable=brain_var,
                    command=self._on_toggle_changed,
                )
                brain_cb.grid(row=0, column=0, sticky="w")
                brain_summary = ctk.CTkLabel(
                    self._brain_structures_frame,
                    text=ai_feature_summary_brain_structures(),
                    anchor="w",
                    justify="left",
                    wraplength=480,
                    text_color=("gray30", "gray75"),
                )
                brain_summary.grid(row=1, column=0, sticky="w", pady=(2, 0))
                self._summary_labels["enable_brain_structures"] = brain_summary
                self._brain_structures_status = ctk.CTkLabel(
                    self._brain_structures_frame,
                    text="",
                    anchor="w",
                    justify="left",
                    wraplength=480,
                )
                self._brain_structures_status.grid(row=2, column=0, sticky="w", pady=(4, 0))
                self._status_labels["enable_brain_structures"] = self._brain_structures_status
                self._brain_structures_actions = ctk.CTkFrame(self._brain_structures_frame, fg_color="transparent")
                self._action_frames["enable_brain_structures"] = self._brain_structures_actions
                self._brain_structures_frame.grid_remove()

            if key == "enable_face_blur":
                self._license_frame = ctk.CTkFrame(block, fg_color="transparent")
                self._license_frame.grid(row=4, column=0, sticky="ew", padx=_DETAIL_PADX)
                self._license_frame.columnconfigure(0, weight=1)
                self._license_frame.grid_remove()

    def _notify_layout_changed(self) -> None:
        if self._on_layout_changed is not None:
            self._on_layout_changed()

    def _confirm_feature_disable(self, key: str) -> bool:
        titles = {
            "remove_pixel_phi": ai_feature_title_remove_pixel_phi,
            "enable_harmonize": ai_feature_title_harmonize,
            "enable_face_blur": ai_feature_title_face_blur,
            "enable_brain_structures": ai_feature_title_brain_structures,
        }
        title = titles[key]()
        message = _(
            "The downloaded models for this tool will be removed from disk. Are you sure you want to disable it?"
        )
        return messagebox.askyesno(title, message, parent=self.winfo_toplevel())

    def _on_toggle_changed(self) -> None:
        session = get_ai_session()
        if session.remove_pixel_phi and not self._feature_enabled("remove_pixel_phi"):
            if self._feature_download_in_progress("remove_pixel_phi"):
                self._feature_vars["remove_pixel_phi"].set(1)
                messagebox.showwarning(
                    ai_feature_title_remove_pixel_phi(),
                    _("Wait for the OCR model download to finish before disabling this tool."),
                    parent=self.winfo_toplevel(),
                )
                return
            if remove_pixel_phi_has_models():
                if not self._confirm_feature_disable("remove_pixel_phi"):
                    self._feature_vars["remove_pixel_phi"].set(1)
                    return
                remove_ocr_models()
        if session.enable_harmonize and not self._feature_enabled("enable_harmonize"):
            if self._feature_download_in_progress("enable_harmonize"):
                self._feature_vars["enable_harmonize"].set(1)
                messagebox.showwarning(
                    ai_feature_title_harmonize(),
                    _("Wait for the anatomy model download to finish before disabling this tool."),
                    parent=self.winfo_toplevel(),
                )
                return
            if harmonize_has_models():
                if not self._confirm_feature_disable("enable_harmonize"):
                    self._feature_vars["enable_harmonize"].set(1)
                    return
                remove_segmentation_model(TsWeightKind.ANATOMY)
                if brain_structures_has_models():
                    remove_segmentation_model(TsWeightKind.BRAIN_STRUCTURES)
                if "enable_brain_structures" in self._feature_vars:
                    self._feature_vars["enable_brain_structures"].set(0)
        if session.enable_brain_structures and not self._feature_enabled("enable_brain_structures"):
            if self._feature_download_in_progress("enable_brain_structures"):
                self._feature_vars["enable_brain_structures"].set(1)
                messagebox.showwarning(
                    ai_feature_title_brain_structures(),
                    _("Wait for the brain structures model download to finish before disabling this option."),
                    parent=self.winfo_toplevel(),
                )
                return
            if brain_structures_has_models():
                if not self._confirm_feature_disable("enable_brain_structures"):
                    self._feature_vars["enable_brain_structures"].set(1)
                    return
                remove_segmentation_model(TsWeightKind.BRAIN_STRUCTURES)
        if session.enable_face_blur and not self._feature_enabled("enable_face_blur"):
            if self._feature_download_in_progress("enable_face_blur"):
                self._feature_vars["enable_face_blur"].set(1)
                messagebox.showwarning(
                    ai_feature_title_face_blur(),
                    _("Wait for the face model download to finish before disabling this tool."),
                    parent=self.winfo_toplevel(),
                )
                return
            if face_blur_has_models():
                if not self._confirm_feature_disable("enable_face_blur"):
                    self._feature_vars["enable_face_blur"].set(1)
                    return
                remove_segmentation_model(TsWeightKind.FACE)
        self.apply_session()
        self._refresh_status()
        if self._on_flags_changed is not None:
            self._on_flags_changed()

    def _feature_enabled(self, key: str) -> bool:
        return self._feature_vars[key].get() == 1

    def _refresh_status(self) -> None:
        if self._license_validating:
            return
        get_runtime_status(force_refresh=True)

        self._update_feature_status(
            "remove_pixel_phi",
            enabled=self._feature_enabled("remove_pixel_phi"),
            summary=_FEATURE_SUMMARIES["remove_pixel_phi"](),
            status=_FEATURE_STATUS["remove_pixel_phi"](),
            show_download=self._feature_enabled("remove_pixel_phi") and remove_pixel_phi_needs_download(),
            download_command=self._start_ocr_download,
        )
        self._update_feature_status(
            "enable_harmonize",
            enabled=self._feature_enabled("enable_harmonize"),
            summary=_FEATURE_SUMMARIES["enable_harmonize"](),
            status=_FEATURE_STATUS["enable_harmonize"](),
            show_download=self._feature_enabled("enable_harmonize") and harmonize_needs_download(),
            download_command=lambda: self._start_model_download(TsWeightKind.ANATOMY),
        )
        self._refresh_brain_structures_option()
        self._update_feature_status(
            "enable_face_blur",
            enabled=self._feature_enabled("enable_face_blur"),
            summary=_FEATURE_SUMMARIES["enable_face_blur"](),
            status=_FEATURE_STATUS["enable_face_blur"](),
            show_download=self._feature_enabled("enable_face_blur") and face_blur_needs_download(),
            download_command=lambda: self._start_model_download(TsWeightKind.FACE),
        )
        self._refresh_license_entry()
        self._notify_layout_changed()

    def _refresh_brain_structures_option(self) -> None:
        frame = self._brain_structures_frame
        if frame is None or "enable_brain_structures" not in self._feature_vars:
            return
        harmonize_on = self._feature_enabled("enable_harmonize")
        if not harmonize_on:
            frame.grid_remove()
            return
        frame.grid()
        brain_on = self._feature_enabled("enable_brain_structures")
        summary = self._summary_labels.get("enable_brain_structures")
        status = self._status_labels.get("enable_brain_structures")
        if summary is not None:
            summary.configure(text=ai_feature_summary_brain_structures() if brain_on else "")
        if status is not None:
            status.configure(text=ai_feature_status_brain_structures() if brain_on else "")
        self._update_feature_status(
            "enable_brain_structures",
            enabled=brain_on,
            summary=ai_feature_summary_brain_structures(),
            status=ai_feature_status_brain_structures(),
            show_download=brain_on and brain_structures_needs_download(),
            download_command=lambda: self._start_model_download(TsWeightKind.BRAIN_STRUCTURES),
        )

    def _update_feature_status(
        self,
        key: str,
        *,
        enabled: bool,
        summary: str,
        status: str,
        show_download: bool,
        download_command: Callable[[], None],
    ) -> None:
        summary_label = self._summary_labels[key]
        status_label = self._status_labels[key]
        actions = self._action_frames[key]
        show_progress = enabled and self._feature_download_in_progress(key)
        if enabled:
            summary_label.configure(text=summary)
            summary_label.grid()
            status_label.configure(text=status)
            status_label.grid()
        else:
            summary_label.configure(text="")
            summary_label.grid_remove()
            status_label.configure(text="")
            status_label.grid_remove()

        for widget in actions.winfo_children():
            widget.destroy()
        self._progress_bars.pop(key, None)
        self._progress_details.pop(key, None)
        self._progress_indeterminate.pop(key, None)

        if show_progress:
            actions.grid(row=3, column=0, sticky="ew", padx=_DETAIL_PADX, pady=(4, 0))
            actions.columnconfigure(0, weight=1)
            progress = ctk.CTkProgressBar(actions, width=320)
            progress.grid(row=0, column=0, sticky="ew")
            detail = ctk.CTkLabel(
                actions,
                text="",
                anchor="w",
                justify="left",
                wraplength=500,
                text_color=("gray30", "gray75"),
            )
            detail.grid(row=1, column=0, sticky="w", pady=(4, 0))
            self._progress_bars[key] = progress
            self._progress_details[key] = detail
            self._apply_download_progress(key)
        elif enabled and show_download:
            actions.grid(row=3, column=0, sticky="w", padx=_DETAIL_PADX, pady=(4, 0))
            ctk.CTkButton(
                actions,
                text=_("Download models"),
                width=140,
                command=download_command,
            ).grid(row=0, column=0, sticky="w")
        else:
            actions.grid_remove()

    def _refresh_license_entry(self) -> None:
        if self._license_frame is None:
            return
        for widget in self._license_frame.winfo_children():
            widget.destroy()
        self._license_entry = None
        self._license_apply_button = None

        show_license = face_blur_needs_license() and (
            self._feature_enabled("enable_face_blur") or self._feature_enabled("enable_brain_structures")
        )
        if not show_license:
            self._license_frame.grid_remove()
            return

        self._license_frame.grid()

        stored = get_stored_face_license()
        if stored and not self._license_var.get().strip():
            self._license_var.set(stored)

        ctk.CTkLabel(
            self._license_frame,
            text=face_license_request_instructions(),
            anchor="w",
            justify="left",
            wraplength=500,
            text_color=("gray30", "gray75"),
        ).grid(row=0, column=0, sticky="w", pady=(4, 0))

        entry_row = ctk.CTkFrame(self._license_frame, fg_color="transparent")
        entry_row.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        entry_row.columnconfigure(0, weight=1)

        entry = ctk.CTkEntry(entry_row, textvariable=self._license_var, placeholder_text="aca_XXXXXXXXXXXXXX")
        entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._license_entry = entry

        apply_button = ctk.CTkButton(
            entry_row,
            text=_("Apply license"),
            width=120,
            command=self._apply_license,
        )
        apply_button.grid(row=0, column=1, sticky="e")
        self._license_apply_button = apply_button

        if self._license_validating:
            entry.configure(state="disabled")
            apply_button.configure(state="disabled", text=_("Validating…"))

    def _set_license_busy(self, busy: bool) -> None:
        self._license_validating = busy
        if self._license_apply_button is not None:
            self._license_apply_button.configure(
                text=_("Validating…") if busy else _("Apply license"),
                state="disabled" if busy else "normal",
            )
        if self._license_entry is not None:
            self._license_entry.configure(state="disabled" if busy else "normal")
        self._notify_layout_changed()

    def _apply_license(self) -> None:
        if self._license_validating or (self._license_thread is not None and self._license_thread.is_alive()):
            return
        license_number = self._license_var.get().strip()
        format_error = validate_face_license_format(license_number)
        if format_error is not None:
            messagebox.showerror(_("License not saved"), format_error, parent=self.winfo_toplevel())
            return
        self._set_license_busy(True)

        def worker() -> None:
            try:
                ok, message = apply_face_license(license_number)
            except Exception as exc:
                logger.exception("Face license apply failed")
                ok, message = False, str(exc)
            self._worker_queue.put(("license_done", (ok, message)))

        self._license_thread = threading.Thread(target=worker, name="TsegLicenseApply", daemon=True)
        self._license_thread.start()

    def _on_license_applied(self, ok: bool, message: str) -> None:
        self._license_thread = None
        self._set_license_busy(False)
        parent = self.winfo_toplevel()
        if ok:
            messagebox.showinfo(_("License saved"), message, parent=parent)
        else:
            messagebox.showerror(_("License not saved"), message, parent=parent)
        self._refresh_status()

    def _start_model_download(self, kind: TsWeightKind) -> None:
        if self._download_thread is not None and self._download_thread.is_alive():
            logger.info("AI Features: %s model download already in progress", kind.value)
            return
        feature_key = _TS_KIND_FEATURE_KEY.get(kind)
        if feature_key is None:
            return
        logger.info("AI Features: starting %s model download", kind.value)
        self._pending_ts_download = kind
        begin_model_download(feature_key, message=_("Preparing model download…"))

        def worker() -> None:
            result: TsWeightState | None = None
            try:
                result = download_segmentation_model(kind)
            except Exception:
                logger.exception("Segmentation model download failed for %s", kind)
            self._worker_queue.put(("download_done", (kind, result)))

        self._download_thread = threading.Thread(target=worker, name=f"TsegDownload-{kind}", daemon=True)
        self._download_thread.start()
        self._refresh_status()

    def _start_ocr_download(self) -> None:
        if self._ocr_thread is not None and self._ocr_thread.is_alive():
            logger.info("AI Features: OCR model download already in progress")
            return
        logger.info("AI Features: starting OCR model download")
        begin_model_download("remove_pixel_phi", message=_("Preparing OCR model download…"))

        def worker() -> None:
            try:
                download_ocr_models()
            except Exception:
                logger.exception("OCR model download failed")
            self._worker_queue.put(("ocr_done", None))

        self._ocr_thread = threading.Thread(target=worker, name="OcrDownload", daemon=True)
        self._ocr_thread.start()
        self._refresh_status()

    def _drain_worker_queue(self) -> None:
        while True:
            try:
                kind, payload = self._worker_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "license_done":
                ok, message = payload
                self._on_license_applied(ok, message)
            elif kind == "download_done":
                ts_kind, result = payload
                feature_key = _TS_KIND_FEATURE_KEY.get(ts_kind)
                self._download_thread = None
                self._pending_ts_download = None
                if feature_key is not None:
                    end_model_download(feature_key)
                    final_state = refresh_weight_status(ts_kind)
                    if result is not None and result.status != TsWeightStatus.READY:
                        logger.warning(
                            "AI Features: %s model download failed: %s",
                            ts_kind.value,
                            result.detail or result.status.value,
                        )
                        self._show_download_error(ts_kind, result)
                    elif final_state.status != TsWeightStatus.READY:
                        logger.warning(
                            "AI Features: %s model download incomplete: %s",
                            ts_kind.value,
                            final_state.detail or final_state.status.value,
                        )
                        self._show_download_error(ts_kind, final_state)
                    else:
                        logger.info("AI Features: %s model download finished successfully", ts_kind.value)
                self._refresh_status()
                self.update_idletasks()
            elif kind == "ocr_done":
                self._ocr_thread = None
                end_model_download("remove_pixel_phi")
                from anonymizer.controller.ai.remove_pixel_phi import ocr_models_ready

                if not ocr_models_ready():
                    logger.warning("AI Features: OCR model download did not complete")
                    messagebox.showerror(
                        ai_feature_title_remove_pixel_phi(),
                        _("OCR model download did not complete. Check your network connection and try again."),
                        parent=self.winfo_toplevel(),
                    )
                else:
                    logger.info("AI Features: OCR model download finished successfully")
                self._refresh_status()

    def _show_download_error(self, kind: TsWeightKind, state: TsWeightState) -> None:
        titles = {
            TsWeightKind.ANATOMY: ai_feature_title_harmonize,
            TsWeightKind.FACE: ai_feature_title_face_blur,
            TsWeightKind.BRAIN_STRUCTURES: ai_feature_title_brain_structures,
        }
        title_fn = titles.get(kind)
        if title_fn is None:
            return
        detail = state.detail.strip() if state.detail else _("Model download did not complete.")
        messagebox.showerror(title_fn(), detail, parent=self.winfo_toplevel())

    def _feature_download_in_progress(self, key: str) -> bool:
        if is_model_download_active(key):
            return True
        if key == "remove_pixel_phi" and self._ocr_thread is not None:
            return True
        if key == "enable_harmonize" and self._pending_ts_download == TsWeightKind.ANATOMY:
            return True
        if key == "enable_brain_structures" and self._pending_ts_download == TsWeightKind.BRAIN_STRUCTURES:
            return True
        return key == "enable_face_blur" and self._pending_ts_download == TsWeightKind.FACE

    def _download_detail_message(self, key: str) -> str:
        progress = get_model_download_progress(key)
        if progress is not None and progress.message:
            return progress.message
        status = get_runtime_status()
        if key == "enable_harmonize":
            return status.anatomy_weights.detail
        if key == "enable_face_blur":
            return status.face_weights.detail
        if key == "enable_brain_structures":
            return status.brain_structures_weights.detail
        if key == "remove_pixel_phi":
            return _("Downloading OCR models…")
        return _("Downloading…")

    def _apply_download_progress(self, key: str) -> None:
        progress_bar = self._progress_bars.get(key)
        detail_label = self._progress_details.get(key)
        if progress_bar is None or detail_label is None:
            return

        progress = get_model_download_progress(key)
        detail_label.configure(text=self._download_detail_message(key))

        if progress is not None and progress.fraction is not None:
            if self._progress_indeterminate.get(key):
                progress_bar.stop()
                self._progress_indeterminate[key] = False
            progress_bar.configure(mode="determinate")
            progress_bar.set(max(0.0, min(1.0, progress.fraction)))
            return

        if not self._progress_indeterminate.get(key):
            progress_bar.configure(mode="indeterminate")
            progress_bar.start()
            self._progress_indeterminate[key] = True

    def _update_download_progress(self) -> bool:
        active = False
        for key in ("remove_pixel_phi", "enable_harmonize", "enable_brain_structures", "enable_face_blur"):
            in_progress = self._feature_download_in_progress(key)
            if key in self._progress_bars and not in_progress:
                self._refresh_status()
                return False
            if not in_progress:
                continue
            active = True
            if key not in self._progress_bars:
                self._refresh_status()
                return active
            self._apply_download_progress(key)
        return active

    def _schedule_poll(self) -> None:
        if self._destroyed:
            return
        self._drain_worker_queue()
        self._update_download_progress()
        self._poll_after_id = self.after(self.POLL_MS, self._schedule_poll)
