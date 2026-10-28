"""Report Text Review: Detect / Remove / Save for native SR and Encapsulated PDF."""

import contextlib
import logging
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import Literal

import customtkinter as ctk
from pydicom import Dataset, dcmread

from anonymizer.controller.ai.embedded_phi.ner.engine import REPLACE_MODE_VALUES, Entity, ReplaceMode
from anonymizer.controller.ai.embedded_phi.report.process_report_text import (
    _SLOT_SEP,
    detect_phi,
    encapsulated_pdf_bytes,
    extract_report_text,
    remove_phi,
    write_report_text,
)
from anonymizer.controller.ai.feature_availability import harmonize_allowed_for_modality, report_text_phi_ready
from anonymizer.controller.project import ProjectController
from anonymizer.utils.dicom import DeidMethodCode, record_deid_method_codes
from anonymizer.utils.storage.dicom_tree import get_dcm_files
from anonymizer.utils.translate import _
from anonymizer.view.ai.harmonize_description import (
    harmonize_button_visible,
    harmonize_description_button_label,
    launch_harmonize_description,
)
from anonymizer.view.ai.harmonize_results import HarmonizeBatchOutcome
from anonymizer.view.common.app_window import AppCTkToplevel, refresh_app_window_menu
from anonymizer.view.common.ctk_safe import mark_ctk_window_destroyed
from anonymizer.view.common.fonts import AppFonts
from anonymizer.view.common.navigation import find_dataset_view_parent, return_to_dataset_view
from anonymizer.view.common.phi_action_labels import (
    detect_phi_button_label,
    remove_phi_button_label,
    replace_mode_labels,
)
from anonymizer.view.common.tooltip import bind_hover_tooltip
from anonymizer.view.common.ux_fields import button_width_for_label, truncate_series_description
from anonymizer.view.reports.pdf_page_view import PdfPageView
from anonymizer.view.reports.report_canvas import ReportCanvas
from anonymizer.view.series.metadata_assessment_dialog import MetadataAssessmentDialog

logger = logging.getLogger(__name__)

DocumentKind = Literal["sr", "pdf"]


def _display_report_text(text: str) -> str:
    """Show slot separator as newlines when extract used \\x1e (embedded newlines)."""

    body = str(text or "")
    if _SLOT_SEP in body and _SLOT_SEP != "\n":
        return body.replace(_SLOT_SEP, "\n")
    return body


class ReportTextReview(AppCTkToplevel):
    """Detect → Remove (Blank|Synthetic) → Save; text side panel with entity highlights."""

    PAD = 10
    BUTTON_WIDTH = 140
    POLL_MS = 100
    DEFAULT_WIDTH = 1100
    DEFAULT_HEIGHT = 720
    _MAX_SCREEN_HEIGHT_FRACTION = 0.75

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
        self._document_kind: DocumentKind = document_kind
        self._destroyed = False
        self._detecting = False
        self._detect_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._mode_labels = replace_mode_labels()

        self._dcm_path: Path | None = None
        self._ds: Dataset | None = None
        self._text = ""
        self._entities: list[Entity] = []
        self._excluded_starts: set[int] = set()
        self._dirty = False
        self._removed_since_save = False
        self._removed_phi_texts: list[str] = []
        self._harmonize_view = None

        self.pdf_view: PdfPageView | None = None
        self.text_panel: ReportCanvas | None = None
        self.harmonize_button: ctk.CTkButton | None = None

        self._update_title()
        self._page_kind = document_kind == "pdf"
        self.minsize(720, 520)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Escape>", lambda _event: self._on_cancel())

        width, height = self._window_size()
        self.geometry(f"{width}x{height}")
        if self._page_kind:
            # Wait for PDF raster before showing (avoids empty-frame flash).
            self.withdraw()

        self._build_ui()
        self._load_content()
        self._refresh_state()
        if not self._page_kind:
            self.lift()

    def _window_size(self) -> tuple[int, int]:
        """Sensible startup size for the current display (not full A4 page)."""
        try:
            sw = int(self.winfo_screenwidth())
            sh = int(self.winfo_screenheight())
        except tk.TclError:
            return self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT
        w = min(self.DEFAULT_WIDTH, max(800, int(sw * 0.65)))
        h = min(self.DEFAULT_HEIGHT, max(520, int(sh * self._MAX_SCREEN_HEIGHT_FRACTION)))
        return w, h

    def _on_pdf_pages_ready(self) -> None:
        """Show the window once pages are ready; PDF fits the panel and scrolls."""
        if self.pdf_view is None:
            return
        self.pdf_view._on_pages_ready = None
        self.deiconify()
        self.lift()
        self.update_idletasks()
        self.pdf_view._refit()

    def _update_title(self) -> None:

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

        if self._page_kind:
            body.grid_columnconfigure(0, weight=3)
            body.grid_columnconfigure(1, weight=2)
            self.pdf_view = PdfPageView(body, on_pages_ready=self._on_pdf_pages_ready)
            self.pdf_view.grid(row=0, column=0, sticky="nsew", padx=(0, pad // 2))
            self.text_panel = ReportCanvas(body, on_toggle=self._on_toggle_entity)
            self.text_panel.grid(row=0, column=1, sticky="nsew", padx=(pad // 2, 0))
        else:
            body.grid_columnconfigure(0, weight=1)
            self.text_panel = ReportCanvas(body, on_toggle=self._on_toggle_entity)
            self.text_panel.grid(row=0, column=0, sticky="nsew")

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
        self.mode_menu.grid(row=0, column=2, padx=(2, pad), pady=0)

        self.remove_button.grid_remove()
        self.mode_menu.grid_remove()

        metadata_label = _("Metadata")
        self.metadata_button = ctk.CTkButton(
            action_group,
            width=button_width_for_label(metadata_label, minimum=self.BUTTON_WIDTH),
            text=metadata_label,
            command=self._on_metadata,
        )
        self.metadata_button.grid(row=0, column=3, padx=(2, pad), pady=0)
        bind_hover_tooltip(
            self.metadata_button,
            _("View DICOM metadata for this report."),
            parent=self,
        )

        self.status_label = ctk.CTkLabel(self.control_frame, text="", anchor="w", justify="left")
        self.status_label.grid(row=1, column=0, padx=pad, pady=(0, pad), sticky="w")

        footer_right = ctk.CTkFrame(self.control_frame, fg_color="transparent")
        footer_right.grid(row=1, column=2, padx=pad, pady=(0, pad), sticky="e")
        self.harmonize_button = ctk.CTkButton(
            footer_right,
            width=160,
            text=harmonize_description_button_label(),
            command=self._on_harmonize_description,
        )
        self.harmonize_button.grid(row=0, column=0, padx=(0, 2), pady=0, sticky="e")
        self.harmonize_button.grid_remove()

        self.save_button = ctk.CTkButton(footer_right, width=110, text=_("Save"), command=self._on_save)
        self.save_button.grid(row=0, column=1, padx=(2, 0), pady=0, sticky="e")

    def _load_content(self) -> None:
        paths = get_dcm_files(self._series_path)
        if not paths:
            if self.text_panel is not None:
                self.text_panel.show_text("", empty_message=_("No DICOM files in this series."))
            return
        self._dcm_path = paths[0]
        self._ds = dcmread(self._dcm_path)
        pdf_data: bytes | None = None
        if self.pdf_view is not None and self._document_kind == "pdf":
            pdf_data = encapsulated_pdf_bytes(self._ds)
            self.pdf_view.show_pdf_bytes(pdf_data)
            # Empty PDF never fires on_pages_ready (window starts withdrawn).
            if not pdf_data:
                self.deiconify()
                self.lift()
        try:
            text = extract_report_text(self._ds)
        except ValueError as exc:
            logger.warning("report view: extract failed: %s", exc)
            text = ""
        self._text = text
        self._entities = []
        if self.text_panel is not None:
            self.text_panel.show_text(
                _display_report_text(text),
                empty_message=_("No extractable report text found."),
            )
        if not str(text or "").strip():
            logger.warning(
                "report view: no extractable report text path=%s kind=%s",
                self._dcm_path,
                self._document_kind,
            )
            if self._document_kind == "pdf" and not pdf_data:
                self._set_status(
                    _(
                        "No encapsulated PDF in this file. "
                        "Enable Clean Structured Content and re-import to keep the document for review."
                    )
                )
            else:
                self._set_status(_("No extractable report text found."))
        elif self._document_kind == "pdf":
            self._set_status(_("PDF loaded. Click Detect PHI."))
        else:
            self._set_status(_("Report text loaded. Click Detect PHI."))

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

    def _active_entities(self) -> list[Entity]:
        return [e for e in self._entities if e.start not in self._excluded_starts]

    def _sync_highlights(self) -> None:
        if self.text_panel is None:
            return
        self.text_panel.highlight(self._entities, lambda start: start in self._excluded_starts)

    def _anon_series_uid(self) -> str | None:
        if self._ds is None:
            return None
        uid = str(getattr(self._ds, "SeriesInstanceUID", "") or "").strip()
        return uid or None

    def _harmonize_button_visible(self) -> bool:
        anon_uid = self._anon_series_uid()
        already = anon_uid is not None and self._controller.series_is_harmonized(anon_uid)
        modality = getattr(self._ds, "Modality", None) if self._ds is not None else None
        return harmonize_button_visible(
            harmonize_models_ready=harmonize_allowed_for_modality(modality),
            modality=modality,
            already_harmonized=already,
        )

    def _set_harmonize_button_present(self, present: bool) -> None:
        if self.harmonize_button is None:
            return
        try:
            mapped = bool(self.harmonize_button.winfo_ismapped())
        except tk.TclError:
            return
        if present and not mapped:
            with contextlib.suppress(tk.TclError):
                self.harmonize_button.grid()
                self.harmonize_button.configure(state="normal")
        elif not present and mapped:
            with contextlib.suppress(tk.TclError):
                self.harmonize_button.grid_remove()

    def _refresh_state(self) -> None:
        has_detections = bool(self._entities)
        has_active = bool(self._active_entities())
        show_remove = has_detections and self._ds is not None and not self._detecting
        self._set_remove_toolbar_present(show_remove)
        self.detect_button.configure(state="disabled" if self._detecting else "normal")
        if show_remove:
            self.remove_button.configure(state="normal" if has_active else "disabled")
            self.mode_menu.configure(state="normal")
        self.metadata_button.configure(
            state="disabled" if (self._ds is None or self._detecting) else "normal"
        )
        self.save_button.configure(
            state="normal" if (self._ds is not None and (self._dirty or self._removed_since_save)) else "disabled"
        )
        self._set_harmonize_button_present(self._harmonize_button_visible() and not self._detecting)
        self._refresh_remove_label()
        self._sync_highlights()

    def _on_metadata(self) -> None:
        """Open the Metadata tree for the loaded report DICOM file."""
        if self._ds is None or self._dcm_path is None:
            return
        try:
            ds = dcmread(str(self._dcm_path), stop_before_pixels=True, force=True)
        except Exception:
            logger.exception("Could not read metadata for report %s", self._dcm_path)
            ds = self._ds
        MetadataAssessmentDialog(
            self,
            dataset=ds,
            dataset_path=self._dcm_path,
            project_dir=self._controller.model.storage_dir,
            modality=str(getattr(ds, "Modality", "") or "") or None,
        )

    def _on_series_description_updated(self) -> None:
        self._update_title()
        dataset = find_dataset_view_parent(self)
        if dataset is not None:
            with contextlib.suppress(tk.TclError):
                dataset._update_tree_from_phi_index()

    def _on_harmonize_closed(self, _outcome: HarmonizeBatchOutcome) -> None:
        self._harmonize_view = None
        if self._destroyed or not self.winfo_exists():
            return
        # Reload header attrs (SeriesDescription) after Accept.
        if self._dcm_path is not None:
            with contextlib.suppress(Exception):
                self._ds = dcmread(self._dcm_path, stop_before_pixels=True)
        self._refresh_state()
        self._update_title()

    def _on_harmonize_description(self) -> None:
        if not self._harmonize_button_visible():
            return

        def _before_open() -> None:
            self._set_harmonize_button_present(False)

        view = launch_harmonize_description(
            self,
            series_path=self._series_path,
            ds=self._ds,
            anon_model=self._controller.anonymizer.model,
            fonts=self._fonts,
            mappings_dir=self._controller.model.mappings_dir(),
            existing_view=self._harmonize_view,
            on_series_description_updated=self._on_series_description_updated,
            on_closed=self._on_harmonize_closed,
            on_before_open=_before_open,
        )
        if view is not None:
            self._harmonize_view = view

    def _set_status(self, text: str) -> None:
        if not self._destroyed:
            self.status_label.configure(text=text)

    def _on_toggle_entity(self, start: int) -> None:
        if start in self._excluded_starts:
            self._excluded_starts.discard(start)
            self._set_status(_("Included for Remove") + ". " + _("Click to exclude."))
        else:
            self._excluded_starts.add(start)
            self._set_status(_("Excluded from Remove") + ". " + _("Click again to include."))
        self._refresh_state()

    def _on_detect(self) -> None:
        if self._detecting or self._ds is None:
            return
        if not report_text_phi_ready():
            messagebox.showwarning(
                _("Embedded PHI"),
                _("Embedded PHI models are not downloaded. Install them under AI Features."),
                parent=self,
            )
            return
        self._detecting = True
        self._refresh_state()
        self._set_status(_("Detecting…"))
        ds = self._ds

        def _worker() -> None:
            try:
                phi_header = None
                with contextlib.suppress(Exception):
                    study_uid = str(getattr(ds, "StudyInstanceUID", "") or "")
                    if study_uid:
                        phi_header = self._controller.anonymizer.model.get_study_phi_header_by_anon_study_uid(
                            study_uid
                        )
                self._detect_queue.put(("ok", detect_phi(ds, phi_header=phi_header)))
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
        self._detecting = False
        if kind == "error":
            self._set_status(_("Detection failed") + f": {payload}")
            self._refresh_state()
            return
        text, entities = payload  # type: ignore[misc]
        self._text = text
        self._entities = list(entities)
        self._excluded_starts.clear()
        if self.text_panel is not None:
            self.text_panel.show_text(
                _display_report_text(text),
                empty_message=_("No extractable report text found."),
            )
        self._refresh_state()
        if not str(text or "").strip():
            self._set_status(_("No extractable report text found."))
        elif not entities:
            self._set_status(_("No PHI detected."))
        else:
            self._set_status(
                _("Detection complete")
                + f" ({len(entities)}). "
                + _("Click a highlight to exclude it from Remove.")
            )

    def _on_remove(self) -> None:
        active = self._active_entities()
        if not active:
            return
        for ent in active:
            frag = self._text[ent.start : ent.end]
            if frag.strip() and frag not in self._removed_phi_texts:
                self._removed_phi_texts.append(frag)
        synthetic = self._selected_mode() == "synth"
        self._text = remove_phi(self._text, active, synthetic=synthetic)
        self._entities = []
        self._excluded_starts.clear()
        self._dirty = True
        self._removed_since_save = True
        if self.text_panel is not None:
            self.text_panel.show_text(self._text)
        self._refresh_state()
        self._set_status(_("Removed Embedded PHI") + f" ({len(active)}). " + _("Save to write changes."))

    def _on_save(self) -> None:
        if self._ds is None or self._dcm_path is None:
            return
        sr = write_report_text(self._ds, self._text)
        record_deid_method_codes(self._ds, {DeidMethodCode.CLEAN_STRUCTURED_CONTENT})
        record_deid_method_codes(sr, {DeidMethodCode.CLEAN_STRUCTURED_CONTENT})
        self._ds.save_as(self._dcm_path, enforce_file_format=True)
        out_dir = self._series_path.parent / str(sr.SeriesInstanceUID)
        out_dir.mkdir(parents=True, exist_ok=True)
        sr_path = out_dir / f"{sr.SOPInstanceUID}.dcm"
        sr.save_as(sr_path, enforce_file_format=True)

        anon_model = self._controller.anonymizer.model
        if self._removed_since_save and self._removed_phi_texts:
            with contextlib.suppress(Exception):
                anon_model.set_instance_embedded_phi(str(self._ds.SOPInstanceUID), self._removed_phi_texts)
                anon_model.set_series_embedded_phi_scanned(str(self._ds.SeriesInstanceUID), scanned=True)
        self._removed_phi_texts.clear()
        self._removed_since_save = False
        self._dirty = False

        if self.pdf_view is not None and self._document_kind == "pdf":
            data = encapsulated_pdf_bytes(self._ds)
            self.pdf_view.show_pdf_bytes(data, notify_ready=False, keep_display_width=True)

        self._refresh_state()
        self._set_status(_("Changes saved") + " — " + _("Basic Text SR written for research use"))
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
        if self._dirty and not messagebox.askyesno(
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
