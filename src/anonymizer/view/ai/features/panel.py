"""AI Features setup: download / remove models and license (no enable preferences)."""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox

import customtkinter as ctk

from anonymizer.controller.ai.remove_pixel_phi import ocr_models_ready
from anonymizer.controller.ai.tseg.config import (
    get_ct_segmentation_mode,
    get_mr_segmentation_mode,
    set_ct_segmentation_mode,
    set_mr_segmentation_mode,
)
from anonymizer.controller.ai.tseg.readiness import (
    apply_face_license,
    get_stored_face_license,
    weight_kind_ready,
)
from anonymizer.utils.storage import get_model_download_progress
from anonymizer.utils.translate import _
from anonymizer.view.ai.features.availability import (
    DownloadCompleteEvent,
    face_blur_needs_license,
    face_license_request_instructions,
    get_download_manager,
    segmentation_mode_from_menu_label,
    segmentation_mode_menu_label,
    segmentation_mode_menu_values,
    validate_face_license_format,
)
from anonymizer.view.ai.features.catalog import (
    AiFeatureId,
    AiModelGroupId,
    all_download_ids,
    feature_spec,
    group_by_download_id,
    groups_for,
    model_group_spec,
    top_level_features,
    weight_kind_for_download_id,
)

logger = logging.getLogger(__name__)

_FEATURE_PADY = (0, 6)
_DETAIL_PADX = (16, 0)
_NESTED_PADX = (8, 0)


class AiFeaturesPanel(ctk.CTkFrame):
    """Model install status, download/remove, and Face license."""

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
        self._download_manager = get_download_manager()
        self._license_thread: threading.Thread | None = None
        self._license_validating = False
        self._poll_after_id: str | None = None
        self._destroyed = False
        self._license_var = tk.StringVar(value=get_stored_face_license())
        self._summary_labels: dict[str, ctk.CTkLabel] = {}
        self._status_labels: dict[str, ctk.CTkLabel] = {}
        self._action_frames: dict[str, ctk.CTkFrame] = {}
        self._progress_frames: dict[str, ctk.CTkFrame] = {}
        self._progress_bars: dict[str, ctk.CTkProgressBar] = {}
        self._progress_details: dict[str, ctk.CTkLabel] = {}
        self._progress_indeterminate: dict[str, bool] = {}
        self._modality_frames: dict[str, ctk.CTkFrame] = {}
        self._resolution_frames: dict[str, ctk.CTkFrame] = {}
        self._resolution_menus: dict[str, ctk.CTkOptionMenu] = {}
        self._license_frame: ctk.CTkFrame | None = None
        self._license_entry: ctk.CTkEntry | None = None
        self._license_apply_button: ctk.CTkButton | None = None
        self._ct_mode_var: tk.StringVar | None = None
        self._mr_mode_var: tk.StringVar | None = None

        self.columnconfigure(0, weight=1)
        self._build_features()
        self.sync_from_runtime()
        self._schedule_poll()

    def sync_from_runtime(self) -> None:
        """Refresh status from on-disk weights."""
        if self._ct_mode_var is not None:
            self._ct_mode_var.set(segmentation_mode_menu_label(get_ct_segmentation_mode()))
        if self._mr_mode_var is not None:
            self._mr_mode_var.set(segmentation_mode_menu_label(get_mr_segmentation_mode()))
        self._refresh_status()

    def apply_session(self) -> None:
        """Apply ephemeral download resolution selections (no project persistence)."""
        if self._ct_mode_var is not None:
            set_ct_segmentation_mode(segmentation_mode_from_menu_label(self._ct_mode_var.get()))
        if self._mr_mode_var is not None:
            set_mr_segmentation_mode(segmentation_mode_from_menu_label(self._mr_mode_var.get()))

    def destroy(self) -> None:
        self._destroyed = True
        if self._poll_after_id is not None:
            self.after_cancel(self._poll_after_id)
        super().destroy()

    def _build_modality_section(
        self,
        parent: ctk.CTkFrame,
        *,
        group_id: AiModelGroupId,
        row: int,
    ) -> ctk.CTkFrame:
        group = model_group_spec(group_id)
        key = group.download_id
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", padx=_DETAIL_PADX, pady=(4, 0))
        frame.columnconfigure(0, weight=1)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text=group.title(), anchor="w", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, sticky="w"
        )

        if group.has_resolution_picker:
            if group.id == AiModelGroupId.HARMONIZE_CT:
                self._ct_mode_var = tk.StringVar(value=segmentation_mode_menu_label(get_ct_segmentation_mode()))
                mode_var = self._ct_mode_var

                def on_changed(_value: str | None = None) -> None:
                    self._on_segmentation_mode_changed(modality="CT")

            else:
                self._mr_mode_var = tk.StringVar(value=segmentation_mode_menu_label(get_mr_segmentation_mode()))
                mode_var = self._mr_mode_var

                def on_changed(_value: str | None = None) -> None:
                    self._on_segmentation_mode_changed(modality="MR")

            menu = ctk.CTkOptionMenu(
                header,
                variable=mode_var,
                values=list(segmentation_mode_menu_values()),
                command=on_changed,
                dynamic_resizing=False,
                width=84,
            )
            menu.grid(row=0, column=1, sticky="e", padx=(8, 0))
            self._resolution_menus[key] = menu
            # Keep a handle so refresh can show/hide with the section.
            self._resolution_frames[key] = menu

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=0, column=2, sticky="e", padx=(8, 0))
        self._action_frames[key] = actions

        # Nested groups: status only (no long summary); hidden when empty.
        summary = ctk.CTkLabel(frame, text="", anchor="w", justify="left", wraplength=460, height=1)
        summary.grid(row=1, column=0, sticky="w")
        summary.grid_remove()
        self._summary_labels[key] = summary
        status = ctk.CTkLabel(
            frame,
            text="",
            anchor="w",
            justify="left",
            wraplength=460,
            text_color=("gray30", "gray75"),
        )
        status.grid(row=2, column=0, sticky="w", pady=(1, 0))
        self._status_labels[key] = status

        progress = ctk.CTkFrame(frame, fg_color="transparent")
        progress.grid(row=3, column=0, sticky="ew", pady=(2, 0))
        progress.columnconfigure(0, weight=1)
        progress.grid_remove()
        self._progress_frames[key] = progress

        self._modality_frames[key] = frame
        return frame

    def _on_segmentation_mode_changed(self, *, modality: str) -> None:
        if modality == "CT" and self._ct_mode_var is not None:
            set_ct_segmentation_mode(segmentation_mode_from_menu_label(self._ct_mode_var.get()))
        elif modality == "MR" and self._mr_mode_var is not None:
            set_mr_segmentation_mode(segmentation_mode_from_menu_label(self._mr_mode_var.get()))
        self._refresh_status()

    def _build_features(self) -> None:
        for row, feature in enumerate(top_level_features()):
            block = ctk.CTkFrame(self, fg_color="transparent")
            block.grid(row=row, column=0, sticky="ew", pady=_FEATURE_PADY)
            block.columnconfigure(0, weight=1)

            key = feature.id.value
            header = ctk.CTkFrame(block, fg_color="transparent")
            header.grid(row=0, column=0, sticky="ew")
            header.columnconfigure(0, weight=1)
            ctk.CTkLabel(header, text=feature.title(), anchor="w", font=ctk.CTkFont(weight="bold")).grid(
                row=0, column=0, sticky="w"
            )
            actions = ctk.CTkFrame(header, fg_color="transparent")
            actions.grid(row=0, column=1, sticky="e")
            self._action_frames[key] = actions

            summary = ctk.CTkLabel(
                block,
                text="",
                anchor="w",
                justify="left",
                wraplength=480,
                text_color=("gray30", "gray75"),
            )
            summary.grid(row=1, column=0, sticky="w", padx=_DETAIL_PADX, pady=(1, 0))
            self._summary_labels[key] = summary
            status = ctk.CTkLabel(block, text="", anchor="w", justify="left", wraplength=480)
            status.grid(row=2, column=0, sticky="w", padx=_DETAIL_PADX, pady=(1, 0))
            self._status_labels[key] = status
            progress = ctk.CTkFrame(block, fg_color="transparent")
            progress.grid(row=6, column=0, sticky="ew", padx=_DETAIL_PADX, pady=(2, 0))
            progress.columnconfigure(0, weight=1)
            progress.grid_remove()
            self._progress_frames[key] = progress

            if feature.id == AiFeatureId.REMOVE_PIXEL_PHI:
                pass
            elif feature.id == AiFeatureId.HARMONIZE:
                self._build_modality_section(block, group_id=AiModelGroupId.HARMONIZE_CT, row=3)
                self._build_modality_section(block, group_id=AiModelGroupId.BRAIN_STRUCTURES, row=4)
                self._build_modality_section(block, group_id=AiModelGroupId.HARMONIZE_MR, row=5)
            elif feature.id == AiFeatureId.FACE_BLUR:
                self._build_modality_section(block, group_id=AiModelGroupId.FACE_CT, row=3)
                self._build_modality_section(block, group_id=AiModelGroupId.FACE_MR, row=4)
                self._license_frame = ctk.CTkFrame(block, fg_color="transparent")
                self._license_frame.grid(row=5, column=0, sticky="ew", padx=_DETAIL_PADX)
                self._license_frame.columnconfigure(0, weight=1)
                self._license_frame.grid_remove()

    def _notify_layout_changed(self) -> None:
        if self._on_layout_changed is not None:
            self._on_layout_changed()

    def _download_busy(self) -> bool:
        return self._download_manager.busy()

    def _warn_download_busy(self, title: str) -> None:
        messagebox.showwarning(
            title,
            _("Wait for the current model download to finish before starting another."),
            parent=self.winfo_toplevel(),
        )

    def _refresh_status(self) -> None:
        if self._license_validating:
            return
        download_busy = self._download_busy()

        for feature in top_level_features():
            key = feature.id.value
            if feature.id == AiFeatureId.REMOVE_PIXEL_PHI:
                group = model_group_spec(AiModelGroupId.OCR)
                self._update_feature_status(
                    key,
                    summary=feature.summary(),
                    status=feature.status(),
                    show_download=group.needs_download() and not download_busy,
                    show_remove=group.has_models() and not download_busy,
                    download_command=lambda g=group: self._start_group_download(g.id),
                    remove_command=lambda g=group: self._remove_group(g.id),
                )
                continue

            self._update_feature_status(
                key,
                summary=feature.summary(),
                status=feature.status(),
                show_download=False,
                show_remove=False,
                download_command=lambda: None,
                remove_command=lambda: None,
            )
            for group in groups_for(feature.id):
                self._refresh_modality_section(group, download_busy=download_busy)
            if feature.id == AiFeatureId.HARMONIZE:
                self._refresh_modality_section(
                    model_group_spec(AiModelGroupId.BRAIN_STRUCTURES),
                    download_busy=download_busy,
                )

        self._refresh_license_entry()
        self._notify_layout_changed()

    def _refresh_modality_section(self, group, *, download_busy: bool) -> None:
        key = group.download_id
        frame = self._modality_frames.get(key)
        if frame is None:
            return
        frame.grid()
        resolution_frame = self._resolution_frames.get(key)
        if resolution_frame is not None:
            if group.id == AiModelGroupId.HARMONIZE_CT and self._ct_mode_var is not None:
                self._ct_mode_var.set(segmentation_mode_menu_label(get_ct_segmentation_mode()))
            if group.id == AiModelGroupId.HARMONIZE_MR and self._mr_mode_var is not None:
                self._mr_mode_var.set(segmentation_mode_menu_label(get_mr_segmentation_mode()))
            resolution_frame.grid()
        self._update_feature_status(
            key,
            summary="",
            status=group.status(),
            show_download=group.needs_download() and not download_busy,
            show_remove=group.has_models() and not download_busy,
            download_command=lambda gid=group.id: self._start_group_download(gid),
            remove_command=lambda gid=group.id: self._remove_group(gid),
        )

    def _update_feature_status(
        self,
        key: str,
        *,
        summary: str,
        status: str,
        show_download: bool,
        show_remove: bool,
        download_command: Callable[[], None],
        remove_command: Callable[[], None],
        actions_row: int = 3,
        actions_padx: tuple[int, int] = _DETAIL_PADX,
    ) -> None:
        del actions_row, actions_padx  # Actions sit on the model title row.
        summary_label = self._summary_labels[key]
        status_label = self._status_labels[key]
        actions = self._action_frames[key]
        progress_host = self._progress_frames.get(key)
        show_progress = self._download_manager.is_in_progress(key)

        summary_label.configure(text=summary)
        if summary:
            summary_label.grid()
        else:
            summary_label.grid_remove()
        if status:
            status_label.configure(text=status)
            status_label.grid()
        else:
            status_label.configure(text="")
            status_label.grid_remove()

        for widget in actions.winfo_children():
            widget.destroy()
        if progress_host is not None:
            for widget in progress_host.winfo_children():
                widget.destroy()
            progress_host.grid_remove()
        self._progress_bars.pop(key, None)
        self._progress_details.pop(key, None)
        self._progress_indeterminate.pop(key, None)

        if show_progress and progress_host is not None:
            actions.grid()
            progress_host.grid()
            progress_host.columnconfigure(0, weight=1)
            progress = ctk.CTkProgressBar(progress_host, width=320)
            progress.grid(row=0, column=0, sticky="ew")
            detail = ctk.CTkLabel(
                progress_host,
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
        elif show_download or show_remove:
            actions.grid()
            col = 0
            if show_download:
                ctk.CTkButton(
                    actions,
                    text=_("Download"),
                    width=90,
                    command=download_command,
                ).grid(row=0, column=col, sticky="e")
                col += 1
            if show_remove:
                ctk.CTkButton(
                    actions,
                    text=_("Remove"),
                    width=72,
                    command=remove_command,
                ).grid(row=0, column=col, sticky="e", padx=(6, 0) if col else (0, 0))
        else:
            actions.grid_remove()

    def _remove_group(self, group_id: AiModelGroupId) -> None:
        group = model_group_spec(group_id)
        if self._download_busy():
            self._warn_download_busy(group.title())
            return
        if not messagebox.askyesno(
            group.title(),
            _("The downloaded models for this tool will be removed from disk. Are you sure?"),
            parent=self.winfo_toplevel(),
        ):
            return
        group.remove()
        self._refresh_status()
        if self._on_flags_changed is not None:
            self._on_flags_changed()

    def _refresh_license_entry(self) -> None:
        if self._license_frame is None:
            return
        for widget in self._license_frame.winfo_children():
            widget.destroy()
        self._license_entry = None
        self._license_apply_button = None

        if not face_blur_needs_license():
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
        ).grid(row=0, column=0, sticky="ew", pady=(4, 0))

        entry_row = ctk.CTkFrame(self._license_frame, fg_color="transparent")
        entry_row.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        entry_row.columnconfigure(0, weight=1)
        entry = ctk.CTkEntry(entry_row, textvariable=self._license_var, width=320)
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
        if self._on_flags_changed is not None:
            self._on_flags_changed()

    def _start_group_download(self, group_id: AiModelGroupId) -> None:
        group = model_group_spec(group_id)
        if self._download_busy():
            self._warn_download_busy(group.title())
            return
        self.apply_session()
        logger.info("AI Features: starting download for %s", group.download_id)
        started = self._download_manager.start(
            group.download_id,
            group.download,
            on_complete=lambda event: self._worker_queue.put(("download_done", event)),
            preparing_message=_("Preparing model download…"),
        )
        if not started:
            self._warn_download_busy(group.title())
            return
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
                event = payload
                assert isinstance(event, DownloadCompleteEvent)
                self._on_download_complete(event)

    def _on_download_complete(self, event: DownloadCompleteEvent) -> None:
        self._download_manager.clear_pending(event.download_id)
        group = group_by_download_id(event.download_id)
        weight_kind = weight_kind_for_download_id(event.download_id)

        if weight_kind is not None:
            ready = weight_kind_ready(weight_kind)
            if event.error is not None:
                logger.warning("AI Features: %s download failed: %s", event.download_id, event.error)
                self._show_download_error_message(
                    group.title() if group else event.download_id,
                    str(event.error),
                )
            elif not ready:
                self._show_download_error_message(
                    group.title() if group else event.download_id,
                    _("Model download did not complete."),
                )
            else:
                logger.info("AI Features: %s model download finished successfully", event.download_id)
        else:
            if event.error is not None or not ocr_models_ready():
                logger.warning("AI Features: OCR model download did not complete")
                messagebox.showerror(
                    feature_spec(AiFeatureId.REMOVE_PIXEL_PHI).title(),
                    _("OCR model download did not complete. Check your network connection and try again."),
                    parent=self.winfo_toplevel(),
                )
            else:
                logger.info("AI Features: OCR model download finished successfully")
        self._refresh_status()
        if self._on_flags_changed is not None:
            self._on_flags_changed()
        self.update_idletasks()

    def _show_download_error_message(self, title: str, detail: str) -> None:
        messagebox.showerror(title, detail, parent=self.winfo_toplevel())

    def _download_detail_message(self, key: str) -> str:
        progress = get_model_download_progress(key)
        if progress is not None and progress.message:
            return progress.message
        if key == AiModelGroupId.OCR.value:
            return _("Downloading OCR models…")
        return _("Downloading. This may take several minutes.")

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
        for key in all_download_ids():
            in_progress = self._download_manager.is_in_progress(key)
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
