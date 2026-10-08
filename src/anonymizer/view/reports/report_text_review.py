"""Report Text Review: Series View–aligned workspace for SR / PDF / pixel reports."""

from __future__ import annotations

import contextlib
import logging
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import TYPE_CHECKING

import customtkinter as ctk
from pydicom import dcmread

from anonymizer.controller.ai.embedded_phi.ner.replace import (
    REPLACE_MODE_VALUES,
    ReplaceMode,
    replace_mode_display_label,
)
from anonymizer.controller.ai.embedded_phi.report.report_session import DocumentKind, ReportSession
from anonymizer.controller.ai.feature_availability import (
    embedded_phi_has_models,
    report_text_phi_ready,
)
from anonymizer.utils.storage import get_dcm_files
from anonymizer.utils.translate import _
from anonymizer.view.common.app_window import AppCTkToplevel, refresh_app_window_menu
from anonymizer.view.common.ctk_safe import mark_ctk_window_destroyed
from anonymizer.view.common.navigation import find_dataset_view_parent, return_to_dataset_view
from anonymizer.view.common.tooltip import bind_hover_tooltip
from anonymizer.view.reports.pdf_page_view import PdfPageView
from anonymizer.view.reports.report_canvas import ReportCanvas

if TYPE_CHECKING:
    from anonymizer.controller.project import ProjectController
    from anonymizer.view.common.fonts import AppFonts

logger = logging.getLogger(__name__)


def replace_mode_labels() -> dict[str, ReplaceMode]:
    return {replace_mode_display_label(mode): mode for mode in REPLACE_MODE_VALUES}


def detect_phi_button_label() -> str:
    return _("Detect PHI")


def remove_phi_button_label(mode: ReplaceMode) -> str:
    if mode == "synth":
        return _("Replace PHI")
    return _("Remove PHI")


class ReportTextReview(AppCTkToplevel):
    """Detect → zones → Remove (Blank|Synthetic) → Save."""

    PAD = 10
    BUTTON_WIDTH = 140
    POLL_MS = 100
    DEFAULT_WIDTH = 1100
    DEFAULT_HEIGHT = 900

    def __init__(
        self,
        parent: tk.Misc,
        *,
        controller: ProjectController,
        series_path: Path,
        document_kind: DocumentKind = "sr",
        fonts: AppFonts | None = None,
    ) -> None:
        super().__init__(master=parent)
        self._parent = parent
        self._fonts = fonts
        self._controller = controller
        self._series_path = Path(series_path)
        self._destroyed = False
        self._detecting = False
        self._detect_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.session = ReportSession(self._series_path, document_kind)
        self._mode_labels = replace_mode_labels()
        self.pdf_view: PdfPageView | None = None
        self.canvas: ReportCanvas | None = None

        self._update_title()
        self._page_kind = document_kind in {"pdf", "pixel_report"}
        self.minsize(720, 520)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Escape>", lambda _event: self._on_cancel())

        # Page reports: hide until sized once (avoids default→resize startup flicker).
        if self._page_kind:
            self.withdraw()
        else:
            width, height = self._window_size()
            self.geometry(f"{width}x{height}")

        self._build_ui()
        self._load_content()
        self._refresh_state()
        self._set_status(self._initial_status())
        if not self._page_kind:
            self.lift()

    def _window_size(self) -> tuple[int, int]:
        try:
            sw = int(self.winfo_screenwidth())
            sh = int(self.winfo_screenheight())
        except tk.TclError:
            return self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT
        w = min(self.DEFAULT_WIDTH, max(800, int(sw * 0.65)))
        h = min(self.DEFAULT_HEIGHT, max(640, int(sh * 0.85)))
        return w, h

    def _size_window_to_page(self) -> None:
        """One-shot size to page aspect, paint once, then show (no resize flicker)."""
        if self.pdf_view is None:
            return
        aspect = self.pdf_view.first_page_aspect()
        if aspect is None or aspect <= 0:
            # Disconnect so later Remove/Save previews do not re-enter sizing.
            self.pdf_view._on_pages_ready = None
            self.deiconify()
            self.lift()
            return
        try:
            sw = int(self.winfo_screenwidth())
            sh = int(self.winfo_screenheight())
        except tk.TclError:
            sw, sh = 1440, 900
        chrome_w = 2 * self.PAD + 28
        chrome_h = 2 * self.PAD + 120
        max_w = max(720, int(sw * 0.88) - chrome_w)
        max_h = max(520, int(sh * 0.92) - chrome_h)
        page_w = min(max_w, int(max_h / aspect))
        page_w = max(640, page_w)
        page_h = int(page_w * aspect)
        if page_h > max_h:
            page_h = max_h
            page_w = max(640, int(page_h / aspect))
        self.geometry(f"{page_w + chrome_w}x{page_h + chrome_h}")
        self.pdf_view._suspend_configure_refit = True
        try:
            # Target width before map so first paint is correct while withdrawn.
            self.pdf_view._display_width = page_w
            self.update_idletasks()
            self.pdf_view._refit()
        finally:
            self.pdf_view._suspend_configure_refit = False
        # One-shot only — Remove/Save must not re-size the window.
        self.pdf_view._on_pages_ready = None
        self.deiconify()
        self.lift()
        # Ignore Configure storms right after map (geometry settle).
        self.pdf_view._suspend_configure_refit = True
        self.after(120, self._release_configure_refit)

    def _release_configure_refit(self) -> None:
        if self.pdf_view is not None:
            self.pdf_view._suspend_configure_refit = False

    def _update_title(self) -> None:
        from anonymizer.view.common.ux_fields import truncate_series_description

        title = _("Report Text Review")
        try:
            paths = get_dcm_files(self._series_path)
            if paths:
                ds = dcmread(paths[0], stop_before_pixels=True)
                patient_id = str(getattr(ds, "PatientID", "") or "").strip()
                series_desc = truncate_series_description(ds.get("SeriesDescription", ""))
                phi = None
                if patient_id:
                    with contextlib.suppress(Exception):
                        phi = self._controller.get_phi_by_anon_patient_id(patient_id)
                if phi:
                    title += f" for {phi.patient_name} {patient_id}"
                    if series_desc:
                        title += f" {series_desc}"
                    title += " "
                elif patient_id or series_desc:
                    title += f" — {patient_id} {series_desc}".rstrip()
        except Exception:  # noqa: BLE001
            logger.debug("Report title: could not read series DICOM", exc_info=True)
            title += f" — {self._series_path.name}"
        self.title(title)
        with contextlib.suppress(Exception):
            refresh_app_window_menu(self)

    def _build_ui(self) -> None:
        pad = self.PAD
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._sv_frame = ctk.CTkFrame(self)
        self._sv_frame.grid(row=0, column=0, padx=pad, pady=pad, sticky="nsew")
        self._sv_frame.grid_rowconfigure(0, weight=1)
        self._sv_frame.grid_columnconfigure(0, weight=1)

        body = ctk.CTkFrame(self._sv_frame, fg_color="transparent")
        body.grid(row=0, column=0, sticky="nsew", padx=pad, pady=(pad, 0))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)

        is_page = self.session.document_kind in {"pdf", "pixel_report"}
        if is_page:
            self.pdf_view = PdfPageView(
                body,
                on_toggle_hit=self._on_toggle_hit,
                on_delete_exclude=self._on_delete_exclude,
                on_pending_rects=self._on_pending_changed,
                on_pages_ready=self._size_window_to_page,
            )
            self.pdf_view.grid(row=0, column=0, sticky="nsew")
        else:
            self.canvas = ReportCanvas(body, on_toggle=self._on_toggle_entity)
            self.canvas.grid(row=0, column=0, sticky="nsew")

        # Bottom control frame — Series View order
        self.control_frame = ctk.CTkFrame(self._sv_frame)
        self.control_frame.grid(row=1, column=0, sticky="ew", padx=pad, pady=pad)
        self.control_frame.grid_columnconfigure(0, weight=0)
        self.control_frame.grid_columnconfigure(1, weight=1)
        self.control_frame.grid_columnconfigure(2, weight=0)

        action_group = ctk.CTkFrame(self.control_frame, fg_color="transparent")
        action_group.grid(row=0, column=0, padx=(0, pad), pady=pad, sticky="w")

        self.detect_button = ctk.CTkButton(
            action_group, width=self.BUTTON_WIDTH, text=detect_phi_button_label(), command=self._on_detect
        )
        self.detect_button.grid(row=0, column=0, padx=(pad, 2), pady=0)

        self.remove_button = ctk.CTkButton(
            action_group,
            width=self.BUTTON_WIDTH,
            text=remove_phi_button_label("blank"),
            command=self._on_remove,
        )
        self.remove_button.grid(row=0, column=1, padx=2, pady=0)

        labels = list(self._mode_labels)
        self.mode_var = tk.StringVar(value=labels[0])
        self.mode_menu = ctk.CTkOptionMenu(
            action_group,
            values=labels,
            variable=self.mode_var,
            width=120,
            command=lambda _v: self._refresh_remove_label(),
        )
        self.mode_menu.grid(row=0, column=2, padx=2, pady=0)

        # Series View: hide Remove + mode until Detect has results.
        self.remove_button.grid_remove()
        self.mode_menu.grid_remove()

        self.blackout_button = ctk.CTkButton(
            action_group,
            width=self.BUTTON_WIDTH,
            text=_("Blackout Area"),
            command=self._on_blackout,
        )
        self.blackout_button.grid(row=0, column=3, padx=2, pady=0)
        bind_hover_tooltip(
            self.blackout_button,
            _(
                "Fill drawn rectangles with the page background. Draw a rectangle first, then click."
            ),
            parent=self,
        )

        self.exclude_button = ctk.CTkButton(
            action_group,
            width=self.BUTTON_WIDTH,
            text=_("Exclude Area"),
            command=self._on_exclude,
        )
        self.exclude_button.grid(row=0, column=4, padx=(2, pad), pady=0)
        bind_hover_tooltip(
            self.exclude_button,
            _(
                "Skip drawn rectangles during Detect. Pixels are not changed. "
                "Draw a rectangle first, then click. Click a dotted outline to delete it."
            ),
            parent=self,
        )

        if not is_page:
            self.blackout_button.configure(state="disabled")
            self.exclude_button.configure(state="disabled")

        self.status_label = ctk.CTkLabel(self.control_frame, text="", anchor="w", justify="left")
        self.status_label.grid(row=1, column=0, columnspan=2, padx=pad, pady=(0, pad), sticky="w")

        self.save_button = ctk.CTkButton(self.control_frame, width=110, text=_("Save"), command=self._on_save)
        self.save_button.grid(row=1, column=2, padx=pad, pady=(0, pad), sticky="e")

    def _load_content(self) -> None:
        if self.pdf_view is not None and self.session.document_kind == "pdf":
            data = self.session.pdf_bytes()
            widths = None
            self.pdf_view.show_pdf_bytes(data, page_widths=widths)
        elif self.canvas is not None:
            self.canvas.show_slots(
                self.session.slots,
                empty_message=_("No text found in this series."),
                show_headers=len(self.session.slots) > 1,
            )

    def _initial_status(self) -> str:
        if self.session.document_kind == "pdf":
            return _("PDF loaded. Click Detect PHI.")
        if self.session.document_kind == "pixel_report":
            return _("Pixel report loaded. Click Detect PHI.")
        return _("Report text loaded. Click Detect PHI.")

    def _selected_mode(self) -> ReplaceMode:
        return self._mode_labels.get(self.mode_var.get(), REPLACE_MODE_VALUES[0])

    def _refresh_remove_label(self) -> None:
        self.remove_button.configure(text=remove_phi_button_label(self._selected_mode()))

    def _set_remove_toolbar_present(self, present: bool) -> None:
        for widget in (self.remove_button, self.mode_menu):
            try:
                mapped = bool(widget.winfo_ismapped())
            except tk.TclError:
                continue
            if present and not mapped:
                with contextlib.suppress(tk.TclError):
                    widget.grid()
            elif not present and mapped:
                with contextlib.suppress(tk.TclError):
                    widget.grid_remove()

    def _sync_overlays(self) -> None:
        if self.pdf_view is not None:
            self.pdf_view.set_overlays(
                self.session.hits,
                excluded_keys=self.session.excluded_hit_keys,
                exclude_rects=self.session.exclude_rects,
                blackout_rects=self.session.blackout_rects,
                pending=self.session.pending_draw_rects,
            )
        if self.canvas is not None:
            self.canvas.highlight(
                self.session.scans,
                lambda key, start: (key, start) in self.session.excluded,
            )

    def _refresh_state(self) -> None:
        s = self.session
        has_detections = bool(s.hits if s.document_kind != "sr" else s.scans)
        has_active = bool(s.active_hits() if s.document_kind != "sr" else s.active_scans())
        # Show Remove only after Detect produced hits (Series View parity).
        show_remove = has_detections and s.can_edit and not self._detecting
        self._set_remove_toolbar_present(show_remove)
        self.detect_button.configure(state="disabled" if self._detecting else "normal")
        if show_remove:
            self.remove_button.configure(state="normal" if has_active else "disabled")
            self.mode_menu.configure(state="normal")
        self.save_button.configure(
            state="normal" if (s.can_edit and (s.dirty or s.removed_since_save)) else "disabled"
        )
        self._refresh_remove_label()
        self._sync_overlays()

    def _set_status(self, text: str) -> None:
        if not self._destroyed:
            self.status_label.configure(text=text)

    def _flush_view_pending(self) -> None:
        if self.pdf_view is None:
            return
        self.session.pending_draw_rects.extend(self.pdf_view.take_pending())

    def _on_pending_changed(self) -> None:
        self._flush_view_pending()
        self._sync_overlays()

    def _on_blackout(self) -> None:
        self._flush_view_pending()
        n = self.session.commit_blackout_pending()
        self._sync_overlays()
        if n:
            self._set_status(_("Blackout area(s) added") + f": {n}")
            self._refresh_state()
        else:
            self._set_status(_("No blackout area(s) — draw a rectangle first"))

    def _on_exclude(self) -> None:
        self._flush_view_pending()
        n = self.session.commit_exclude_pending()
        self._sync_overlays()
        if n:
            self._set_status(_("Exclude area(s) added") + f": {n}")
        else:
            self._set_status(_("No exclude area(s) — draw a rectangle first"))

    def _on_delete_exclude(self, x: int, y: int) -> bool:
        if self.session.remove_exclude_rect_at(x, y):
            self._sync_overlays()
            self._set_status(_("Exclude area removed"))
            return True
        return False

    def _on_toggle_hit(self, key: str) -> None:
        self.session.toggle_hit_excluded(key)
        excluded = key in self.session.excluded_hit_keys
        self._refresh_state()
        if excluded:
            self._set_status(_("Excluded from Remove") + ". " + _("Click again to include."))
        else:
            self._set_status(_("Included for Remove") + ". " + _("Click to exclude."))

    def _on_toggle_entity(self, slot_key: str, start: int) -> None:
        self.session.toggle_excluded(slot_key, start)
        self._refresh_state()

    def _on_detect(self) -> None:
        if self._detecting:
            return
        # PDF/SR: NER only. pixel_report: OCR ∧ NER.
        ready = (
            embedded_phi_has_models()
            if self.session.document_kind == "pixel_report"
            else report_text_phi_ready()
        )
        if not ready:
            messagebox.showwarning(
                _("Embedded PHI"),
                _("Embedded PHI models are not downloaded. Install them under AI Features."),
                parent=self,
            )
            return
        self._detecting = True
        self._refresh_state()
        self._set_status(_("Detecting…"))

        def _progress(msg: str) -> None:
            self._detect_queue.put(("progress", msg))

        def _worker() -> None:
            try:
                self._detect_queue.put(("ok", self.session.detect(progress=_progress)))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Report Text Review detect failed")
                self._detect_queue.put(("error", str(exc)))

        threading.Thread(target=_worker, name="ReportDetect", daemon=True).start()
        self.after(self.POLL_MS, self._poll_detect)

    def _poll_detect(self) -> None:
        if self._destroyed:
            return
        try:
            kind, payload = self._detect_queue.get_nowait()
        except queue.Empty:
            self.after(self.POLL_MS, self._poll_detect)
            return
        if kind == "progress":
            self._set_status(str(payload))
            self.after(self.POLL_MS, self._poll_detect)
            return
        self._detecting = False
        if kind == "error":
            self._set_status(_("Detection failed") + f": {payload}")
            self._refresh_state()
            return
        self._refresh_state()
        excluded = len(self.session.exclude_rects)
        msg = _("Detection complete. Click a highlight to exclude it from Remove.")
        if excluded:
            msg += f" ({excluded} " + _("exclude zone(s)") + ")"
        self._set_status(msg)

    def _on_remove(self) -> None:
        mode = self._selected_mode()
        try:
            changed = self.session.remove(
                mode,
                project_id=str(getattr(self._controller.model, "site_id", "default")),
            )
        except RuntimeError as exc:
            messagebox.showinfo(title=_("Report Text Review"), message=str(exc), parent=self)
            return
        if self.canvas is not None:
            self.canvas.show_slots(
                self.session.slots,
                show_headers=len(self.session.slots) > 1,
            )
        if self.pdf_view is not None and self.session.document_kind == "pdf":
            preview = self.session.preview_redacted_pdf()
            if preview:
                self.pdf_view.show_pdf_bytes(
                    preview, notify_ready=False, keep_display_width=True
                )
                self.pdf_view.set_overlays([], excluded_keys=set())
        self._refresh_state()
        self._set_status(_("Removed Embedded PHI") + f" ({changed}). " + _("Save to write changes."))

    def _on_save(self) -> None:
        saved = self.session.save(self._controller.anonymizer.model)
        if self.pdf_view is not None and self.session.document_kind == "pdf":
            self.pdf_view.show_pdf_bytes(
                self.session.pdf_bytes(), notify_ready=False, keep_display_width=True
            )
        self._refresh_state()
        note = _("Changes saved")
        if self.session.document_kind in {"pdf", "pixel_report"} and len(saved) > 1:
            note += " — " + _("Basic Text SR written for research use")
        self._set_status(note)
        dataset = find_dataset_view_parent(self)
        if dataset is not None:
            with contextlib.suppress(tk.TclError):
                dataset._update_tree_from_phi_index()

    def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        if self.pdf_view is not None:
            with contextlib.suppress(Exception):
                self.pdf_view.clear()
        mark_ctk_window_destroyed(self)
        super().destroy()

    def _on_cancel(self) -> None:
        if self.session.dirty and not messagebox.askyesno(
            title=_("Report Text Review"),
            message=_("Discard unsaved changes?"),
            parent=self,
        ):
            return
        with contextlib.suppress(tk.TclError):
            self.grab_release()
        return_to_dataset_view(self)
        self.destroy()


def show_report_text_review(
    parent: tk.Misc,
    *,
    controller: ProjectController,
    series_path: Path,
    document_kind: DocumentKind = "sr",
    fonts: AppFonts | None = None,
) -> ReportTextReview | None:
    if not Path(series_path).is_dir():
        messagebox.showerror(
            title=_("Report Text Review"),
            message=_("Could not load this series.") + f"\n\n{series_path}",
            parent=parent,
        )
        return None
    return ReportTextReview(
        parent, controller=controller, series_path=series_path, document_kind=document_kind, fonts=fonts
    )
