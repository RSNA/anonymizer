"""Shot handlers for MkDocs help screenshot capture."""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any, Callable

from docs_help.capture import (
    CaptureContext,
    ShotResult,
    _ensure_project,
    _fixture_from_deps,
    _import_fixtures,
    _open_settings,
)
from docs_help.manifest import ShotSpec
from docs_help.orthanc import (
    assert_orthanc_reachable,
    seed_orthanc_ct,
    seed_orthanc_if_empty,
)
from docs_help.platform import close_toplevel, settle, wait_mapped
from docs_help.project_setup import (
    CTP_LOOKUP_PROPERTIES,
    collect_import_paths,
    create_capture_project,
    series_for_fixture,
    study_tuples,
)

logger = logging.getLogger("docs_help")


def shot_welcome(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    dest = ctx.grab(ctx.app, shot)
    return ShotResult(shot.id, "ok", "WelcomeView", dest)


def shot_new_project_settings(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    dlg = _open_settings(ctx, new_model=True)
    try:
        return ShotResult(shot.id, "ok", "SettingsDialog", ctx.grab(dlg, shot))
    finally:
        close_toplevel(dlg)


def shot_settings_subdialog(ctx: CaptureContext, shot: ShotSpec, opener: Callable) -> ShotResult:
    settings = _open_settings(ctx, new_model=False)
    try:
        settle(settings, ctx.settle_ms)
        dlg = opener(settings)
        try:
            settle(dlg, ctx.settle_ms)
            return ShotResult(shot.id, "ok", shot.window, ctx.grab(dlg, shot))
        finally:
            close_toplevel(dlg)
    finally:
        close_toplevel(settings)


def shot_local_server(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    from anonymizer.utils.translate import _
    from anonymizer.view.settings.dicom_node_dialog import DICOMNodeDialog

    def opener(settings):
        return DICOMNodeDialog(settings, settings.model.scp, title=_("Local Server"))

    return shot_settings_subdialog(ctx, shot, opener)


def shot_query_server(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    from anonymizer.utils.translate import _
    from anonymizer.view.settings.dicom_node_dialog import DICOMNodeDialog

    def opener(settings):
        scp = settings.model.remote_scps[_("QUERY")]
        return DICOMNodeDialog(settings, scp, title=_("Query Server"))

    return shot_settings_subdialog(ctx, shot, opener)


def shot_export_server(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    from anonymizer.utils.translate import _
    from anonymizer.view.settings.dicom_node_dialog import DICOMNodeDialog

    def opener(settings):
        scp = settings.model.remote_scps[_("EXPORT")]
        return DICOMNodeDialog(settings, scp, title=_("Export Server"))

    return shot_settings_subdialog(ctx, shot, opener)


def shot_aws(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    from anonymizer.view.settings.aws_cognito_dialog import AWSCognitoDialog

    def opener(settings):
        return AWSCognitoDialog(settings, settings.model.export_to_AWS, settings.model.aws_cognito)

    return shot_settings_subdialog(ctx, shot, opener)


def shot_network_timeouts(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    from anonymizer.view.settings.network_timeouts_dialog import NetworkTimeoutsDialog

    def opener(settings):
        return NetworkTimeoutsDialog(settings, settings.model.network_timeouts)

    return shot_settings_subdialog(ctx, shot, opener)


def shot_modalities(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    from anonymizer.view.settings.modalites_dialog import ModalitiesDialog

    def opener(settings):
        return ModalitiesDialog(settings, settings.model.modalities)

    return shot_settings_subdialog(ctx, shot, opener)


def shot_storage_classes(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    from anonymizer.view.settings.sop_classes_dialog import SOPClassesDialog

    def opener(settings):
        return SOPClassesDialog(settings, settings.model.storage_classes, settings.model.modalities)

    return shot_settings_subdialog(ctx, shot, opener)


def shot_transfer_syntaxes(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    from anonymizer.view.settings.transfer_syntaxes_dialog import TransferSyntaxesDialog

    def opener(settings):
        return TransferSyntaxesDialog(settings, settings.model.transfer_syntaxes)

    return shot_settings_subdialog(ctx, shot, opener)


def shot_logging_levels(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    from anonymizer.view.settings.logging_levels_dialog import LoggingLevelsDialog

    def opener(settings):
        return LoggingLevelsDialog(settings, settings.model.logging_levels)

    return shot_settings_subdialog(ctx, shot, opener)


def shot_lookup_table(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    from anonymizer.view.settings.lookup_table_dialog import LookupTableDialog

    _ensure_project(ctx)
    if not CTP_LOOKUP_PROPERTIES.is_file():
        raise FileNotFoundError(CTP_LOOKUP_PROPERTIES)
    parent = ctx.app.dashboard or ctx.app
    dlg = LookupTableDialog(parent, project_controller=ctx.app.controller)
    try:
        if not dlg.load_properties_path(CTP_LOOKUP_PROPERTIES, show_errors=False):
            raise RuntimeError("lookup preview failed")
        settle(dlg, ctx.settle_ms)
        return ShotResult(shot.id, "ok", CTP_LOOKUP_PROPERTIES.name, ctx.grab(dlg, shot))
    finally:
        close_toplevel(dlg)


def shot_dashboard(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    _ensure_project(ctx)
    return ShotResult(shot.id, "ok", "Dashboard", ctx.grab(ctx.app, shot))


def shot_ai_features(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    from anonymizer.view.ai.ai_features_dialog import AiFeaturesSetupDialog

    dlg = AiFeaturesSetupDialog(ctx.app)
    try:
        settle(dlg, max(ctx.settle_ms, 800))
        try:
            wait_mapped(dlg)
            dlg._fit_to_content()
        except Exception:
            pass
        settle(dlg, max(ctx.settle_ms, 500))
        return ShotResult(
            shot.id,
            "ok",
            "AiFeaturesSetupDialog",
            ctx.grab(dlg, shot, settle_ms=max(ctx.settle_ms, 700)),
        )
    finally:
        close_toplevel(dlg)


def _project_file_menu(app: Any) -> Any:
    """Return the open-project File submenu from the menu bar."""
    from anonymizer.utils.translate import _

    menu_bar = getattr(app, "menu_bar", None)
    if menu_bar is None:
        raise RuntimeError("No menu_bar on app")
    end = int(menu_bar.index("end") or -1)
    for i in range(end + 1):
        try:
            if menu_bar.type(i) != "cascade":
                continue
            if str(menu_bar.entrycget(i, "label")) == _("File"):
                return menu_bar.nametowidget(menu_bar.entrycget(i, "menu"))
        except Exception:
            continue
    raise RuntimeError("File menu not found")


def _save_rgba(dest: Path, image: Any, widget: Any) -> Path:
    from PIL import Image

    from docs_help.platform.common import display_scale as _display_scale, normalize_for_docs as _normalize_for_docs, to_logical_size as _to_logical_size, trim_transparent as _trim_transparent

    if not isinstance(image, Image.Image):
        raise TypeError("expected PIL Image")
    image = _trim_transparent(image.convert("RGBA"))
    image = _to_logical_size(image, _display_scale(widget))
    image = _normalize_for_docs(image)
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, format="PNG")
    return dest


def shot_import_davidson_menu(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    """Main window File menu open — Import Files / Import Directory."""
    import customtkinter as ctk
    from anonymizer.utils.translate import _

    _ensure_project(ctx)
    settle(ctx.app, ctx.settle_ms)
    # Bring Dashboard forward so the shot is clearly the main app + File menu.
    with contextlib.suppress(Exception):
        if ctx.app.dashboard is not None:
            ctx.app.dashboard.deiconify()
            ctx.app.dashboard.lift()
        ctx.app.deiconify()
        ctx.app.lift()
        ctx.app.focus_force()
    settle(ctx.app, ctx.settle_ms)

    # Native macOS menubar is not grab-friendly; compose a File menu panel over the main window.
    standin = ctk.CTkToplevel(ctx.app)
    try:
        standin.title("")
        standin.overrideredirect(True)
        standin.attributes("-topmost", True)
        ax = int(ctx.app.winfo_rootx()) + 12
        ay = int(ctx.app.winfo_rooty()) + 28
        standin.geometry(f"280x220+{ax}+{ay}")
        standin.resizable(False, False)

        menubar = ctk.CTkFrame(standin, height=28, corner_radius=0, fg_color=("#e8e8e8", "#2b2b2b"))
        menubar.pack(fill="x")
        for label, active in ((_("File"), True), (_("Settings"), False), (_("Help"), False)):
            ctk.CTkLabel(
                menubar,
                text=label,
                width=64,
                fg_color=("#cfe0f5", "#1f538d") if active else "transparent",
                text_color=("#014F8F", "#DCE4EE") if active else ("gray20", "gray80"),
                corner_radius=4,
            ).pack(side="left", padx=4, pady=2)

        panel = ctk.CTkFrame(standin, corner_radius=6, border_width=1, border_color=("gray60", "gray40"))
        panel.pack(fill="both", expand=True, padx=2, pady=(0, 2))
        items = (
            (_("Import Files"), True),
            (_("Import Directory"), False),
            (None, False),
            (_("Clone Project"), False),
            (_("Close Project"), False),
            (None, False),
            (_("Exit"), False),
        )
        for label, highlight in items:
            if label is None:
                ctk.CTkFrame(panel, height=1, fg_color=("gray70", "gray40")).pack(fill="x", padx=8, pady=4)
                continue
            ctk.CTkButton(
                panel,
                text=label,
                anchor="w",
                fg_color=("#3a7ebf", "#1f538d") if highlight else "transparent",
                text_color=("#DCE4EE", "#DCE4EE") if highlight else ("gray14", "gray84"),
                hover=False,
                height=28,
            ).pack(fill="x", padx=4, pady=1)

        # Grab main window + menu overlay (union bbox).
        from docs_help.platform import grab_widgets_union

        settle(standin, max(ctx.settle_ms, 400))
        dest = grab_widgets_union(
            [ctx.app, standin],
            ctx.dest(shot),
            settle_ms=max(ctx.settle_ms, 500),
            allow_placeholder=ctx.allow_placeholder,
            shot_id=shot.id,
        )
        return ShotResult(shot.id, "ok", "File menu on main window", dest)
    finally:
        if standin.winfo_exists():
            close_toplevel(standin)


def shot_import_directory_chooser(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    """Folder chooser navigated to tests/.../test_dcm_files (docs stand-in)."""
    import customtkinter as ctk

    from docs_help.project_setup import TEST_DCM_ROOT
    from anonymizer.utils.translate import _

    _ensure_project(ctx)
    settle(ctx.app, ctx.settle_ms)
    folders = sorted(
        p.name for p in TEST_DCM_ROOT.iterdir() if p.is_dir() and not p.name.startswith(".")
    )
    if not folders:
        raise RuntimeError(f"No folders under {TEST_DCM_ROOT}")
    # Prefer highlighting davidson_cxr when present.
    selected = "davidson_cxr" if "davidson_cxr" in folders else folders[0]

    dlg = ctk.CTkToplevel(ctx.app)
    try:
        dlg.title(_("Import Directory") + " — test_dcm_files")
        dlg.resizable(False, False)
        dlg.attributes("-topmost", True)

        path_bar = ctk.CTkFrame(dlg, height=36)
        path_bar.pack(fill="x", padx=10, pady=(10, 4))
        ctk.CTkLabel(
            path_bar,
            text="…/tests/controller/assets/test_dcm_files",
            anchor="w",
            font=ctk.CTkFont(size=13),
        ).pack(fill="x", padx=8, pady=6)

        list_frame = ctk.CTkFrame(dlg)
        list_frame.pack(fill="x", expand=False, padx=10, pady=4)
        header = ctk.CTkFrame(list_frame, height=28, fg_color=("#dfe7f1", "#1f538d"))
        header.pack(fill="x")
        ctk.CTkLabel(header, text="Name", width=280, anchor="w").pack(side="left", padx=8)
        ctk.CTkLabel(header, text="Kind", width=100, anchor="w").pack(side="left", padx=8)

        # Exact folder rows — no spare grey scroll area.
        body_h = 28 * max(len(folders), 1) + 8
        body = ctk.CTkScrollableFrame(list_frame, height=body_h)
        body.pack(fill="x", expand=False)
        for name in folders:
            row = ctk.CTkFrame(
                body,
                fg_color=("#3a7ebf", "#1f538d") if name == selected else "transparent",
                height=28,
            )
            row.pack(fill="x", pady=1)
            fg = ("#DCE4EE", "#DCE4EE") if name == selected else ("gray14", "gray84")
            ctk.CTkLabel(row, text=name, width=280, anchor="w", text_color=fg).pack(side="left", padx=8)
            ctk.CTkLabel(row, text="Folder", width=100, anchor="w", text_color=fg).pack(side="left", padx=8)

        buttons = ctk.CTkFrame(dlg)
        buttons.pack(fill="x", padx=10, pady=(4, 10))
        ctk.CTkButton(buttons, text=_("Cancel"), width=100, state="disabled").pack(side="right", padx=6)
        ctk.CTkButton(buttons, text=_("Choose"), width=100).pack(side="right", padx=6)

        settle(dlg, max(ctx.settle_ms, 400))
        dlg.update_idletasks()
        req_w = max(int(dlg.winfo_reqwidth()), 520)
        req_h = max(int(dlg.winfo_reqheight()), 200)
        dlg.geometry(f"{req_w}x{req_h}")
        settle(dlg, max(ctx.settle_ms, 300))
        dest = ctx.grab(dlg, shot, settle_ms=max(ctx.settle_ms, 500), geometry=f"{req_w}x{req_h}")
        return ShotResult(shot.id, "ok", f"chooser:{selected}+{len(folders)}folders", dest)
    finally:
        if dlg.winfo_exists():
            close_toplevel(dlg)


def _trim_docs_png_whitespace(path: Path, *, bottom: bool = True, right: bool = False) -> None:
    """Crop near-uniform light grey margins from a saved help PNG."""
    try:
        from PIL import Image
        import numpy as np

        image = Image.open(path).convert("RGB")
        arr = np.asarray(image)
        # Treat near-white / light grey as empty (QueryView chrome).
        empty = (arr[:, :, 0] > 220) & (arr[:, :, 1] > 220) & (arr[:, :, 2] > 220)
        rows = np.where(~empty.all(axis=1))[0]
        cols = np.where(~empty.all(axis=0))[0]
        if rows.size == 0 or cols.size == 0:
            return
        top = int(rows[0])
        left = int(cols[0])
        bottom_i = int(rows[-1]) + 1
        right_i = int(cols[-1]) + 1
        # Keep a small pad; only trim requested sides heavily.
        pad = 8
        y0 = max(0, top - pad) if bottom else 0
        y1 = min(arr.shape[0], bottom_i + pad) if bottom else arr.shape[0]
        x0 = max(0, left - pad) if right else 0
        x1 = min(arr.shape[1], right_i + pad) if right else arr.shape[1]
        cropped = image.crop((x0, y0, x1, y1))
        if cropped.size != image.size:
            cropped.save(path, format="PNG")
            logger.info("Trimmed %s %s → %s", path.name, image.size, cropped.size)
    except Exception as exc:
        logger.warning("Whitespace trim failed for %s: %s", path, exc)


def _fit_query_view_for_capture(view: Any, *, row_count: int, ready: bool = False) -> str:
    """Size QueryView so the results table hugs rows (no tall empty grey pane).

    ``ready`` (empty criteria shot) keeps a short empty table so the layout is clear
    without a large grey band. With results, height matches the row count exactly.
    """
    n = max(0, int(row_count))
    if ready:
        tree_rows = 2
    else:
        tree_rows = min(max(n, 1), 12)
    try:
        view._query_results.configure(height=tree_rows)
    except Exception:
        pass
    try:
        view.grid_rowconfigure(1, weight=0)
        view._results_frame.grid_rowconfigure(0, weight=0)
        view._results_frame.grid_configure(sticky="nwe")
        if getattr(view, "_status_frame", None) is not None:
            view._status_frame.grid_configure(sticky="we")
    except Exception:
        pass
    try:
        view.update_idletasks()
        view.update()
    except Exception:
        pass
    # Hug the status bar bottom — avoid leftover grey below controls.
    try:
        status = getattr(view, "_status_frame", None)
        if status is not None:
            bottom = int(status.winfo_y()) + int(status.winfo_height()) + 4
        else:
            bottom = int(view.winfo_reqheight())
        width = max(1100, min(int(view.winfo_reqwidth()) + 16, 1280))
        height = max(280, min(bottom, 720))
        return f"{width}x{height}"
    except Exception:
        return "1200x360" if ready else "1200x420"


def _fit_import_files_dialog(dlg: Any) -> str:
    """Shrink Import Files dialog so the log box does not leave a tall grey band."""
    try:
        # Prefer a compact log height once the worker is done.
        lines = 0
        with contextlib.suppress(Exception):
            text = dlg._text_box.get("1.0", "end")
            lines = max(1, text.count("\n"))
        target_h = min(max(80, lines * 18 + 24), 280)
        with contextlib.suppress(Exception):
            dlg._text_box.configure(height=target_h)
        dlg.rowconfigure(0, weight=0)
        frame = getattr(dlg, "_frame", None)
        if frame is not None:
            frame.rowconfigure(3, weight=0)
            frame.grid_configure(sticky="nwe")
        dlg.update_idletasks()
        dlg.update()
        if frame is not None:
            w = int(frame.winfo_reqwidth()) + 24
            h = int(frame.winfo_reqheight()) + 24
        else:
            w, h = int(dlg.winfo_reqwidth()), int(dlg.winfo_reqheight())
        return f"{max(520, min(w, 900))}x{max(200, min(h, 480))}"
    except Exception:
        return "720x280"


def _fit_import_studies_dialog(dlg: Any) -> str:
    """Shrink Import Studies dialog to content (no empty grey pane)."""
    try:
        dlg.rowconfigure(0, weight=0)
        dlg.columnconfigure(0, weight=1)
        dlg.columnconfigure(1, weight=0)
        frame = getattr(dlg, "_frame", None)
        if frame is not None:
            frame.grid_configure(sticky="nwe")
    except Exception:
        pass
    try:
        dlg.update_idletasks()
        dlg.update()
        frame = getattr(dlg, "_frame", None)
        if frame is not None:
            w = int(frame.winfo_reqwidth()) + 24
            h = int(frame.winfo_reqheight()) + 24
        else:
            w, h = int(dlg.winfo_reqwidth()), int(dlg.winfo_reqheight())
        # Prefer content width; avoid a wide empty right band.
        width = max(380, min(w, 560))
        height = max(220, min(h, 420))
        return f"{width}x{height}"
    except Exception:
        return "440x300"


def _open_davidson_import_dialog(ctx: CaptureContext, *, stall_seconds: float = 0.0):
    """Open Import Files for davidson_cxr.

    If ``stall_seconds`` > 0, anonymize_file blocks that long so Progress can be
    grabbed while Cancel is still showing (before the success line is written).
    """
    from anonymizer.view.project.import_files_dialog import ImportFilesDialog

    _ensure_project(ctx)
    paths = collect_import_paths("davidson_cxr")
    anon = ctx.app.controller.anonymizer
    real = anon.anonymize_file
    if stall_seconds > 0:

        def _stalled(path, *args, **kwargs):  # type: ignore[no-untyped-def]
            import time

            time.sleep(stall_seconds)
            return real(path, *args, **kwargs)

        anon.anonymize_file = _stalled  # type: ignore[method-assign]
    dlg = ImportFilesDialog(ctx.app, anon, paths)
    return dlg, paths, anon, real, stall_seconds > 0


def shot_import_davidson_done(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    """Import dialog finished: success PHI→ID line and Close."""
    from anonymizer.utils.translate import _ as tr

    if "davidson_cxr" in ctx.imported_keys:
        with contextlib.suppress(Exception):
            ctx.app.close_project()
        settle(ctx.app, ctx.settle_ms)
        project_dir = create_capture_project(ctx.work_dir / "project_davidson_done")
        ctx.app.open_project(project_dir)
        settle(ctx.app, ctx.settle_ms)
        ctx.project_open = True
        ctx.imported_keys.clear()

    dlg, paths, anon, real, stalled = _open_davidson_import_dialog(ctx, stall_seconds=0.0)
    try:
        for _i in range(400):
            settle(ctx.app, 50)
            if not dlg.winfo_exists():
                break
            try:
                btn = str(dlg._cancel_button.cget("text"))
                text = dlg._text_box.get("1.0", "end")
            except Exception:
                btn, text = "", ""
            if getattr(dlg, "_worker_done", False) and btn == tr("Close") and "davidson_cxr" in text:
                break
        settle(dlg, max(ctx.settle_ms, 400))
        geom = _fit_import_files_dialog(dlg)
        with contextlib.suppress(Exception):
            dlg.geometry(geom)
        settle(dlg, 300)
        geom = _fit_import_files_dialog(dlg)
        dest = ctx.grab(dlg, shot, settle_ms=max(ctx.settle_ms, 500), geometry=geom)
        ctx.imported_keys.add("davidson_cxr")
        return ShotResult(shot.id, "ok", f"done {len(paths)} file(s)", dest)
    finally:
        if stalled:
            anon.anonymize_file = real  # type: ignore[method-assign]
        if dlg.winfo_exists():
            close_toplevel(dlg)


def shot_import_directory_log(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    """Import Directory-style multi-file dialog with a populated success/skip log."""
    from collections import defaultdict
    from pathlib import Path

    from anonymizer.utils.translate import _ as tr
    from anonymizer.view.project.import_files_dialog import ImportFilesDialog

    _ensure_project(ctx)
    paths = collect_import_paths("davidson_cxr", "CT_Head_With_Contrast", "chest")
    by_parent: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        by_parent[Path(path).parent.name].append(path)
    sample: list[str] = []
    for group in by_parent.values():
        sample.extend(group[:6])
        if len(sample) >= 18:
            break
    if len(sample) < 6:
        sample = paths[:18]

    dlg = ImportFilesDialog(ctx.app, ctx.app.controller.anonymizer, sample)
    try:
        for _i in range(600):
            settle(ctx.app, 50)
            if not dlg.winfo_exists():
                break
            try:
                btn = str(dlg._cancel_button.cget("text"))
                text = dlg._text_box.get("1.0", "end")
            except Exception:
                btn, text = "", ""
            if getattr(dlg, "_worker_done", False) and btn == tr("Close") and text.strip():
                break
        settle(dlg, max(ctx.settle_ms, 500))
        geom = _fit_import_files_dialog(dlg)
        with contextlib.suppress(Exception):
            dlg.geometry(geom)
        settle(dlg, 300)
        geom = _fit_import_files_dialog(dlg)
        dest = ctx.grab(dlg, shot, settle_ms=max(ctx.settle_ms, 500), geometry=geom)
        ctx.imported_keys.update({"davidson_cxr", "CT_Head_With_Contrast", "chest", "test_dcm_files"})
        return ShotResult(shot.id, "ok", f"directory log {len(sample)} files", dest)
    finally:
        if dlg.winfo_exists():
            close_toplevel(dlg)


def shot_query_retrieve_ready(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    """Dashboard Search → Query window with all controls visible (no results yet)."""
    _ensure_project(ctx)
    assert_orthanc_reachable(ctx.app.controller)
    seed_orthanc_if_empty(ctx.app.controller, collect_import_paths("CT_Head_With_Contrast"))

    ctx.app.query_retrieve()
    settle(ctx.app, ctx.settle_ms)
    view = ctx.app.query_view
    if view is None or not view.winfo_exists():
        raise RuntimeError("QueryView failed")
    try:
        # Clear any leftover results so the ready shot is criteria-focused.
        with contextlib.suppress(Exception):
            view._query_results.delete(*view._query_results.get_children())
        geometry = _fit_query_view_for_capture(view, row_count=0, ready=True)
        try:
            view.geometry(geometry)
        except Exception:
            pass
        settle(view, max(ctx.settle_ms, 300))
        geometry = _fit_query_view_for_capture(view, row_count=0, ready=True)
        try:
            view.geometry(geometry)
            view.lift()
            view.focus_force()
        except Exception:
            pass
        settle(view, max(ctx.settle_ms, 500))
        dest = ctx.grab(view, shot, geometry=geometry, settle_ms=max(ctx.settle_ms, 600))
        return ShotResult(shot.id, "ok", f"QueryRetrieve ready {geometry}", dest)
    finally:
        close_toplevel(view)
        with contextlib.suppress(Exception):
            ctx.app.query_view = None


def shot_import_files(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    """Legacy alias for multi-file import log capture."""
    return shot_import_directory_log(ctx, shot)


def _select_query_patient(view: Any, name_substr: str) -> str:
    """Select the first query result whose PatientName contains ``name_substr`` (case-insensitive)."""
    tree = view._query_results
    keys = list(view._query_results_column_keys)
    try:
        name_idx = keys.index("PatientName")
    except ValueError as exc:
        raise RuntimeError(f"PatientName column missing from query results: {keys}") from exc
    needle = name_substr.casefold()
    for iid in tree.get_children():
        values = tree.item(iid, "values")
        if not values or name_idx >= len(values):
            continue
        if needle in str(values[name_idx]).casefold():
            tree.selection_set(iid)
            tree.focus(iid)
            tree.see(iid)
            with contextlib.suppress(Exception):
                view._tree_select(None)
            return str(iid)
    raise RuntimeError(f"No query row matching PatientName containing {name_substr!r}")


def _shot_by_id(ctx: CaptureContext, shot_id: str) -> ShotSpec | None:
    return next((s for s in ctx.manifest.all_shots() if s.id == shot_id), None)


def _orthanc_ct_workflow(ctx: CaptureContext, primary: ShotSpec) -> ShotResult:
    """CT Query → select Doe^Archibald → Import dialog → green imported row (3 PNGs)."""
    from tkinter import messagebox as tk_messagebox

    from anonymizer.utils.translate import _ as tr
    from anonymizer.view.project.import_studies_dialog import ImportStudiesDialog

    # Fresh project so Doe^Archibald is not already imported/green.
    if ctx.project_open:
        with contextlib.suppress(Exception):
            ctx.app.close_project()
        settle(ctx.app, ctx.settle_ms)
        ctx.project_open = False
        ctx.imported_keys.clear()
    project_dir = create_capture_project(ctx.work_dir / "project_orthanc_ct")
    ctx.app.open_project(project_dir)
    settle(ctx.app, ctx.settle_ms)
    ctx.project_open = True

    assert_orthanc_reachable(ctx.app.controller)
    # Prefer the head CT demo only — fewer rows ⇒ clearer Doe^Archibald selection.
    ct_paths = collect_import_paths("CT_Head_With_Contrast")
    seed_orthanc_ct(ctx.app.controller, ct_paths)

    ctx.app.query_retrieve()
    settle(ctx.app, ctx.settle_ms)
    view = ctx.app.query_view
    if view is None or not view.winfo_exists():
        raise RuntimeError("QueryView failed")

    tk_messagebox.showwarning = lambda *a, **k: "ok"  # type: ignore[assignment]
    tk_messagebox.showerror = lambda *a, **k: "ok"  # type: ignore[assignment]
    tk_messagebox.showinfo = lambda *a, **k: "ok"  # type: ignore[assignment]
    tk_messagebox.askyesno = lambda *a, **k: True  # type: ignore[assignment]
    tk_messagebox.askokcancel = lambda *a, **k: True  # type: ignore[assignment]

    try:
        geometry = _fit_query_view_for_capture(view, row_count=0, ready=False)
        view.geometry(geometry)
        view.lift()
        view.focus_force()
    except Exception:
        pass
    settle(view, ctx.settle_ms)

    if hasattr(view, "_modality_var"):
        view._modality_var.set("CT")
    if hasattr(view, "_move_level_var"):
        view._move_level_var.set("SERIES")
    with contextlib.suppress(Exception):
        if hasattr(view, "_show_imported_studies_switch"):
            view._show_imported_studies_switch.select()

    view._query_button_pressed()
    for _i in range(120):
        settle(ctx.app, 100)
        if not view.busy():
            break

    if not list(view._query_results.get_children()):
        raise RuntimeError("CT Query returned no studies from Orthanc")

    doe_iid = _select_query_patient(view, "Doe^Archibald")
    settle(view, max(ctx.settle_ms, 500))
    n_rows = len(list(view._query_results.get_children()))
    geometry = _fit_query_view_for_capture(view, row_count=n_rows, ready=False)
    try:
        view.geometry(geometry)
    except Exception:
        pass
    settle(view, max(ctx.settle_ms, 300))
    geometry = _fit_query_view_for_capture(view, row_count=n_rows, ready=False)
    try:
        view.geometry(geometry)
        view.lift()
        view.focus_force()
    except Exception:
        pass
    settle(view, max(ctx.settle_ms, 400))

    query_shot = _shot_by_id(ctx, "OrthancCT_Query") or primary
    query_dest = ctx.grab(view, query_shot, geometry=geometry, settle_ms=max(ctx.settle_ms, 600))

    close_label = tr("Close")
    state = {"import_grabbed": False, "closed": False}
    importing_shot = _shot_by_id(ctx, "OrthancCT_Importing")

    def _poll_import_dialog() -> None:
        if state["closed"] or not view.winfo_exists():
            return
        for widget in list(view.winfo_children()) + list(ctx.app.winfo_children()):
            if not isinstance(widget, ImportStudiesDialog):
                continue
            try:
                btn = str(widget._cancel_button.cget("text"))
            except Exception:
                continue
            if btn == close_label:
                if importing_shot is not None and not state["import_grabbed"]:
                    try:
                        # Finished state: keep progress bars filled (blue) so they
                        # do not read as empty grey bands in the help PNG.
                        with contextlib.suppress(Exception):
                            widget._metadata_progress_bar.set(1.0)
                            widget._metadata_progress_bar.configure(progress_color=("#3a7ebf", "#1f538d"))
                            widget._import_progress_bar.set(1.0)
                            widget._metadata_status_label.configure(
                                text_color=("#3a7ebf", "#3a7ebf")
                            )
                            widget._metadata_progress_label.configure(
                                text_color=("#3a7ebf", "#3a7ebf")
                            )
                        geom = _fit_import_studies_dialog(widget)
                        with contextlib.suppress(Exception):
                            widget.geometry(geom)
                        settle(widget, 300)
                        geom = _fit_import_studies_dialog(widget)
                        with contextlib.suppress(Exception):
                            widget.geometry(geom)
                            widget.lift()
                            widget.attributes("-topmost", True)
                        settle(widget, 400)
                        ctx.grab(widget, importing_shot, settle_ms=500, geometry=geom)
                        state["import_grabbed"] = True
                        ctx._orthanc_importing_captured = True  # type: ignore[attr-defined]
                    except Exception as exc:
                        logger.warning("OrthancCT_Importing grab failed: %s", exc)
                logger.info("Auto-closing ImportStudiesDialog after Orthanc import")
                widget._on_cancel()
                state["closed"] = True
                return
        ctx.app.after(350, _poll_import_dialog)

    ctx.app.after(350, _poll_import_dialog)
    # Re-select in case focus drifted.
    view._query_results.selection_set(doe_iid)
    with contextlib.suppress(Exception):
        view._tree_select(None)
    try:
        view._import_button_pressed()
    except Exception as exc:
        logger.warning("Import from Orthanc: %s", exc)

    settle(view, max(ctx.settle_ms, 800))
    n_rows = len(list(view._query_results.get_children()))
    geometry = _fit_query_view_for_capture(view, row_count=n_rows, ready=False)
    try:
        view.geometry(geometry)
    except Exception:
        pass
    settle(view, max(ctx.settle_ms, 300))
    geometry = _fit_query_view_for_capture(view, row_count=n_rows, ready=False)
    try:
        view.geometry(geometry)
        view.lift()
        view.focus_force()
    except Exception:
        pass

    imported_shot = _shot_by_id(ctx, "OrthancCT_Imported")
    if imported_shot is not None:
        ctx.grab(view, imported_shot, geometry=geometry, settle_ms=max(ctx.settle_ms, 600))
        ctx._orthanc_imported_captured = True  # type: ignore[attr-defined]

    n = len(list(view._query_results.get_children()))
    return ShotResult(
        primary.id,
        "ok",
        f"Doe^Archibald CT SERIES workflow studies={n} scp_port={ctx.app.controller.model.scp.port}",
        query_dest,
    )


def shot_orthanc_ct_query(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    return _orthanc_ct_workflow(ctx, shot)


def shot_orthanc_ct_importing(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    dest = ctx.dest(shot)
    if getattr(ctx, "_orthanc_importing_captured", False) and dest.exists() and dest.stat().st_size > 1000:
        return ShotResult(shot.id, "ok", "captured with OrthancCT_Query", dest)
    # Standalone: run full workflow (also writes Query + Imported).
    return _orthanc_ct_workflow(ctx, shot)


def shot_orthanc_ct_imported(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    dest = ctx.dest(shot)
    if getattr(ctx, "_orthanc_imported_captured", False) and dest.exists() and dest.stat().st_size > 1000:
        return ShotResult(shot.id, "ok", "captured with OrthancCT_Query", dest)
    return _orthanc_ct_workflow(ctx, shot)


def shot_query(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    """Back-compat alias for older --only QueryRetrieveImport."""
    return _orthanc_ct_workflow(ctx, shot)


def _fit_dataset_view_for_capture(view: Any, *, study_count: int, series_count: int) -> str:
    """Shrink Dataset so the tree fills the window (no empty grey below last row).

    Treeview defaults to ``height=30`` rows; for help shots size exactly to the
    visible study+series rows and stop frames from expanding vertically.
    """
    visible = max(1, int(study_count) + int(series_count))
    # Exact fit — spare rows paint as empty grey (not present in the live app at default size).
    tree_rows = min(visible, 20)
    try:
        view._tree.configure(height=tree_rows)
    except Exception:
        pass
    try:
        view.grid_rowconfigure(0, weight=0)
        view._index_frame.grid_rowconfigure(0, weight=0)
        view._index_frame.grid_configure(sticky="nwe")
        view._button_frame.grid_configure(sticky="we")
    except Exception:
        pass
    try:
        view.update_idletasks()
        view.update()
    except Exception:
        pass
    try:
        btn = view._button_frame
        bottom = int(btn.winfo_y()) + int(btn.winfo_height()) + 4
        req_w = int(view.winfo_reqwidth())
    except Exception:
        bottom, req_w = 360, 1100
    width = max(980, min(req_w + 20, 1280))
    # Prefer content bottom over reqheight so CTk does not leave a grey strip under the buttons.
    height = max(220, min(bottom, 720))
    return f"{width}x{height}"


def _select_dataset_study(view: Any, *name_substrs: str) -> Any:
    """Select the first study whose label/values/series text match any substring."""
    from anonymizer.view.project.dataset import parse_study_tree_iid

    tree = view._tree
    needles = [n.casefold() for n in name_substrs if n]
    if not needles:
        raise RuntimeError("No Dataset study match substrings provided")
    for iid in tree.get_children(""):
        if parse_study_tree_iid(str(iid)) is None:
            continue
        text = str(tree.item(iid, "text") or "")
        values = tree.item(iid, "values") or ()
        series_bits: list[str] = []
        for child in tree.get_children(iid):
            series_bits.append(str(tree.item(child, "text") or ""))
            series_bits.extend(str(v) for v in (tree.item(child, "values") or ()))
        blob = " ".join([text, *[str(v) for v in values], *series_bits]).casefold()
        if any(needle in blob for needle in needles):
            tree.selection_set(iid)
            tree.focus(iid)
            tree.see(iid)
            return iid
    raise RuntimeError(f"No Dataset study matching any of {list(name_substrs)!r}")


def shot_dataset(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    # Fresh project — shared capture projects may still contain synthetic leftovers.
    _open_clean_demo_project(ctx, dirname="project_view_dataset")
    ctx.app.view()
    settle(ctx.app, max(ctx.settle_ms, 800))
    view = ctx.app.dataset_view
    if view is None:
        raise RuntimeError("DatasetView failed")
    study_count = 0
    series_count = 0
    try:
        from anonymizer.view.project.dataset import parse_study_tree_iid

        tree = view._tree
        view._update_tree_from_phi_index()
        settle(view, ctx.settle_ms)
        expanded: set[str] = set()
        for iid in tree.get_children(""):
            study_count += 1
            tree.item(iid, open=True)
            uid = parse_study_tree_iid(str(iid))
            if uid:
                expanded.add(uid)
            for child in tree.get_children(iid):
                series_count += 1
        view._expanded_study_uids = expanded
        view._update_tree_from_phi_index()
        for iid in tree.get_children(""):
            tree.item(iid, open=True)
            for child in tree.get_children(iid):
                tree.item(child, open=True)
        # Guard: help shots must never show synthetic phantoms.
        for iid in tree.get_children(""):
            blob = " ".join(
                [
                    str(tree.item(iid, "text") or ""),
                    *[str(v) for v in (tree.item(iid, "values") or ())],
                ]
            ).upper()
            if "SYNTHETIC" in blob or "PHANTOM" in blob or "SYN001" in blob:
                raise RuntimeError(f"Dataset shot contains synthetic study: {blob!r}")
    except Exception as exc:
        if "synthetic" in str(exc).lower() or "SYNTHETIC" in str(exc):
            raise
        logger.warning("Dataset tree expand: %s", exc)
    settle(view, max(ctx.settle_ms, 600))
    if study_count != 3:
        raise RuntimeError(f"Dataset demo expects 3 studies (CR/CT/US); got {study_count}")
    geometry = _fit_dataset_view_for_capture(view, study_count=study_count, series_count=series_count)
    try:
        view.geometry(geometry)
    except Exception:
        pass
    settle(view, max(ctx.settle_ms, 400))
    geometry = _fit_dataset_view_for_capture(view, study_count=study_count, series_count=series_count)
    try:
        view.geometry(geometry)
    except Exception:
        pass
    settle(view, max(ctx.settle_ms, 300))
    dest = ctx.grab(view, shot, geometry=geometry, settle_ms=max(ctx.settle_ms, 700))
    return ShotResult(shot.id, "ok", f"{study_count} studies / {series_count} series @ {geometry}", dest)


def _prepare_davidson_edit_dataset(
    ctx: CaptureContext,
    *,
    dirname: str,
) -> tuple[Any, str, str, Path]:
    """Import davidson_cxr, apply Chest AP / XR Chest AP harmonize, return DatasetView + UIDs + series path."""
    import shutil

    from anonymizer.controller.ai.harmonize import (
        apply_harmonized_description,
        apply_harmonized_study_description,
    )
    from docs_help.project_setup import create_capture_project

    project_dir = ctx.work_dir / dirname
    if ctx.project_open:
        with contextlib.suppress(Exception):
            ctx.app.close_project()
        ctx.project_open = False
    if project_dir.exists():
        shutil.rmtree(project_dir)
    create_capture_project(project_dir)
    ctx.app.open_project(project_dir)
    settle(ctx.app, ctx.settle_ms)
    if not ctx.app.controller:
        raise RuntimeError(f"Failed to open {dirname}")
    ctx.project_open = True
    ctx.imported_keys.clear()
    _import_fixtures(ctx, "davidson_cxr")
    controller = ctx.app.controller
    assert controller is not None
    anon = controller.anonymizer.model
    images = Path(controller.model.images_dir())
    series_path = series_for_fixture(images, "davidson_cxr")
    if series_path is None or not series_path.is_dir():
        raise RuntimeError("davidson_cxr series missing for Dataset description edit shot")

    if not apply_harmonized_description(series_path, "Chest AP", anon):
        raise RuntimeError("Failed to apply Chest AP harmonized series description")
    study_root = series_path.parent
    anon_study_uid = study_root.name
    apply_harmonized_study_description(
        study_root,
        "XR Chest AP",
        anon,
        anon_study_uid,
        loinc_number="36572-6",
    )

    ctx.app.view()
    settle(ctx.app, max(ctx.settle_ms, 600))
    view = ctx.app.dataset_view
    if view is None:
        raise RuntimeError("DatasetView failed")
    return view, anon_study_uid, series_path.name, series_path


def _place_docs_description_dropdown(
    view: Any,
    *,
    iid: str,
    choices: list[str],
    geometry: str,
    list_width: int | None = None,
) -> tuple[Any, Any]:
    """Place Combobox + Listbox over a Dataset tree cell (no ttk::Post — avoids settle hangs)."""
    import tkinter as tk
    from tkinter import ttk

    tree = view._tree
    tree.see(iid)
    settle(view, 150)
    bbox = tree.bbox(iid, "#0")
    if not bbox:
        raise RuntimeError(f"No bbox for tree row {iid}")
    parent = tree.master
    x, y, width, height = bbox
    place_x = int(tree.winfo_x() + x)
    place_y = int(tree.winfo_y() + y)
    place_w = max(int(width), list_width or 180)
    place_h = max(int(height), 22)
    combo = ttk.Combobox(parent, values=choices, state="readonly", font=view._fonts.mono)
    combo.set(choices[0])
    combo.place(x=place_x, y=place_y, width=place_w, height=place_h)
    combo.lift()
    list_h = min(22 * len(choices), 176)
    listbox = tk.Listbox(
        parent,
        height=max(1, min(len(choices), 8)),
        font=view._fonts.mono,
        activestyle="dotbox",
        exportselection=False,
    )
    for label in choices:
        listbox.insert("end", label)
    listbox.selection_set(0)
    listbox.activate(0)
    listbox.place(x=place_x, y=place_y + place_h, width=place_w, height=list_h)
    listbox.lift()
    settle(view, max(400, 200))
    return combo, listbox


def shot_dataset_edit_description(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    """Dataset with inline RadLex series-description Combobox open on davidson CXR."""
    from anonymizer.controller.ai.harmonize import series_description_edit_choices
    from anonymizer.view.project.dataset import parse_series_tree_iid, series_tree_iid

    view, anon_study_uid, series_uid, _series_path = _prepare_davidson_edit_dataset(
        ctx,
        dirname="project_view_dataset_edit",
    )
    logger.info("Dataset_EditDescription: DatasetView ready")

    tree = view._tree
    view._update_tree_from_phi_index()
    settle(view, ctx.settle_ms)

    series_iid = series_tree_iid(series_uid)
    study_iid = None
    for iid in tree.get_children(""):
        tree.item(iid, open=True)
        for child in tree.get_children(iid):
            if str(child) == series_iid or parse_series_tree_iid(str(child)) == series_uid:
                series_iid = str(child)
                study_iid = str(iid)
                break
        if study_iid is not None:
            break
    if study_iid is None:
        raise RuntimeError(f"Series iid not found in Dataset tree for {series_uid}")

    view._expanded_study_uids.add(anon_study_uid)
    view._update_tree_from_phi_index()
    tree.item(study_iid, open=True)
    settle(view, max(ctx.settle_ms, 300))

    study_count = len(tree.get_children(""))
    series_count = sum(len(tree.get_children(iid)) for iid in tree.get_children(""))
    geometry = _fit_dataset_view_for_capture(view, study_count=study_count, series_count=max(series_count, 6))
    try:
        view.geometry(geometry)
    except Exception:
        pass
    settle(view, max(ctx.settle_ms, 300))

    pair = view._series_by_uid.get(series_uid)
    modality = pair[1].modality if pair is not None else "CR"
    choices = series_description_edit_choices(modality=modality, current_description="Chest AP")
    if not choices:
        raise RuntimeError("No RadLex series description choices for capture")
    logger.info("Dataset_EditDescription: placing Combobox with %d choices", len(choices))

    combo, listbox = _place_docs_description_dropdown(
        view,
        iid=series_iid,
        choices=choices,
        geometry=geometry,
    )
    logger.info("Dataset_EditDescription: grabbing")
    dest = ctx.grab(view, shot, geometry=geometry, settle_ms=max(ctx.settle_ms, 700))
    with contextlib.suppress(Exception):
        listbox.destroy()
    with contextlib.suppress(Exception):
        combo.destroy()
    return ShotResult(shot.id, "ok", "RadLex series description dropdown on davidson_cxr", dest)


def shot_dataset_edit_study_description(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    """Dataset with inline LOINC study-description Combobox open on davidson CXR."""
    from anonymizer.controller.ai.harmonize import study_description_edit_choices
    from anonymizer.view.project.dataset import parse_study_tree_iid, study_tree_iid

    view, anon_study_uid, _series_uid, _series_path = _prepare_davidson_edit_dataset(
        ctx,
        dirname="project_view_dataset_edit_study",
    )
    logger.info("Dataset_EditStudyDescription: DatasetView ready")

    tree = view._tree
    view._update_tree_from_phi_index()
    settle(view, ctx.settle_ms)

    study_iid = study_tree_iid(anon_study_uid)
    found = False
    for iid in tree.get_children(""):
        if str(iid) == study_iid or parse_study_tree_iid(str(iid)) == anon_study_uid:
            study_iid = str(iid)
            found = True
            tree.item(iid, open=True)
            break
    if not found:
        raise RuntimeError(f"Study iid not found in Dataset tree for {anon_study_uid}")

    view._expanded_study_uids.add(anon_study_uid)
    view._update_tree_from_phi_index()
    tree.item(study_iid, open=True)
    settle(view, max(ctx.settle_ms, 300))

    study_count = len(tree.get_children(""))
    series_count = sum(len(tree.get_children(iid)) for iid in tree.get_children(""))
    geometry = _fit_dataset_view_for_capture(view, study_count=study_count, series_count=max(series_count, 8))
    try:
        view.geometry(geometry)
    except Exception:
        pass
    settle(view, max(ctx.settle_ms, 300))

    anon_model = ctx.app.controller.anonymizer.model  # type: ignore[union-attr]
    pairs = study_description_edit_choices(anon_model, anon_study_uid, minimum=6, top_n=8)
    if not pairs:
        raise RuntimeError("No LOINC study description choices for capture")
    labels: list[str] = []
    for name, code in pairs:
        label = f"{name}  ({code})" if code else name
        if label not in labels:
            labels.append(label)
    # Prefer current XR Chest AP first if present.
    current_label = next((label for label in labels if label.startswith("XR Chest AP")), labels[0])
    labels = [current_label] + [label for label in labels if label != current_label]
    # Keep the shot readable — show a short LOINC menu, not the full CSV pad.
    labels = labels[:8]
    logger.info("Dataset_EditStudyDescription: placing Combobox with %d LOINC choices", len(labels))

    combo, listbox = _place_docs_description_dropdown(
        view,
        iid=study_iid,
        choices=labels,
        geometry=geometry,
        list_width=420,
    )
    logger.info("Dataset_EditStudyDescription: grabbing")
    dest = ctx.grab(view, shot, geometry=geometry, settle_ms=max(ctx.settle_ms, 700))
    with contextlib.suppress(Exception):
        listbox.destroy()
    with contextlib.suppress(Exception):
        combo.destroy()
    return ShotResult(shot.id, "ok", "LOINC study description dropdown on davidson_cxr", dest)


def _find_projection_view(ctx: CaptureContext, dataset_view: Any) -> Any:
    from anonymizer.view.series.projection import ProjectionView

    for _ in range(40):
        for child in list(dataset_view.winfo_children()) + list(ctx.app.winfo_children()):
            if isinstance(child, ProjectionView):
                try:
                    if child.winfo_exists() and child.winfo_viewable():
                        return child
                except Exception:
                    continue
        settle(ctx.app, 100)
    return None


def _open_dataset_for_projections(ctx: CaptureContext) -> Any:
    _import_fixtures(ctx, "davidson_cxr", "CT_Head_With_Contrast", "us_rgb_single_frame")
    _ensure_project(ctx)
    if ctx.app.dataset_view is None or not ctx.app.dataset_view.winfo_exists():
        ctx.app.view()
        settle(ctx.app, max(ctx.settle_ms, 800))
    view = ctx.app.dataset_view
    if view is None:
        raise RuntimeError("DatasetView failed")
    try:
        view._update_tree_from_phi_index()
        settle(view, max(ctx.settle_ms, 300))
    except Exception:
        pass
    return view


def _fit_projection_view_column(proj: Any, *, size: str = "S") -> None:
    """Stack series tiles in one column so multi-study shots stay readable at docs width."""
    from anonymizer.controller.create_projections import ProjectionImageSize, ProjectionImageSizeConfig

    mapping = {
        "S": ProjectionImageSize.SMALL,
        "M": ProjectionImageSize.MEDIUM,
        "L": ProjectionImageSize.LARGE,
    }
    enum = mapping[size]
    tile_w = 3 * int(enum.value[0])
    tile_h = int(enum.value[1])
    n = max(1, int(getattr(proj, "_total_series", 1) or 1))
    # Force unscaled S/M/L so layout math matches the docs table.
    ProjectionImageSizeConfig.set_scaling_factor(1.0)
    proj._pv_frame_width = tile_w + 24  # cols == 1
    proj._pv_frame_height = tile_h * n + 24  # rows >= n → one page
    if hasattr(proj, "_image_size_button"):
        proj._image_size_button.set(size)
    proj._update_image_size(size)
    settle(proj, 400)
    proj.update_idletasks()
    # Hug chrome + stacked tiles (avoid the default 90%-of-screen black frame).
    width = max(tile_w + 48, int(proj.winfo_reqwidth()))
    height = max(tile_h * n + 100, int(proj.winfo_reqheight()))
    try:
        proj.resizable(True, True)
    except Exception:
        pass
    proj.geometry(f"{width}x{height}")
    settle(proj, 300)


def _grab_projection_view(
    ctx: CaptureContext,
    shot: ShotSpec,
    dataset_view: Any,
    *,
    size: str = "M",
    column_layout: bool = False,
) -> ShotResult:
    from anonymizer.view.series.projection import ProjectionView

    dataset_view._view_projections_button_pressed()
    settle(ctx.app, max(ctx.settle_ms, 800))

    proj = _find_projection_view(ctx, dataset_view)
    if proj is None:
        records = dataset_view._selected_study_records()
        if not records:
            raise RuntimeError("View Projections: no study selected")
        proj = ProjectionView(
            dataset_view,
            controller=ctx.app.controller,
            base_dir=ctx.app.controller.model.images_dir(),
            phi_records=records,
            fonts=dataset_view._fonts,
        )
        settle(proj, max(ctx.settle_ms, 800))

    try:
        settle(proj, max(ctx.settle_ms, 1000))
        try:
            if column_layout:
                _fit_projection_view_column(proj, size=size)
            elif hasattr(proj, "_image_size_button"):
                proj._image_size_button.set(size)
                proj._update_image_size(size)
                settle(proj, max(ctx.settle_ms, 800))
        except Exception as exc:
            logger.warning("%s size %s: %s", shot.id, size, exc)
        try:
            wait_mapped(proj)
        except Exception:
            pass
        dest = ctx.grab(proj, shot, settle_ms=max(ctx.settle_ms, 700))
        return ShotResult(shot.id, "ok", proj.title(), dest)
    finally:
        close_toplevel(proj)


def shot_view_projections(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    """Dataset → select CT head study → View Projections window with thumbnails."""
    view = _open_dataset_for_projections(ctx)
    # Prefer multi-slice head CT so projection tiles are meaningful.
    # Study label is often "CT Head W contrast"; series may say "Brain Ax EarlyA".
    _select_dataset_study(view, "Head W", "CT Head", "contrast", "Brain", "EarlyArt", "EarlyA")
    settle(view, max(ctx.settle_ms, 300))
    # Medium tiles read better in help than the default Small size.
    return _grab_projection_view(ctx, shot, view, size="M")


def shot_view_projections_multi(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    """Dataset → multi-select all demo studies → View Projections (S tiles)."""
    from anonymizer.view.project.dataset import parse_study_tree_iid

    view = _open_dataset_for_projections(ctx)
    tree = view._tree
    study_iids = [iid for iid in tree.get_children("") if parse_study_tree_iid(str(iid)) is not None]
    if len(study_iids) < 2:
        raise RuntimeError(f"Need ≥2 Dataset studies for multi projections, got {len(study_iids)}")
    tree.selection_set(*study_iids)
    for iid in study_iids:
        tree.see(iid)
    settle(view, max(ctx.settle_ms, 300))
    # Small tiles in one column — readable after docs width normalize; S highlights S/M/L.
    return _grab_projection_view(ctx, shot, view, size="S", column_layout=True)


def shot_series_review(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    from anonymizer.view.series.series import show_series_view

    fixture = _fixture_from_deps(shot.deps) or "davidson_cxr"
    _import_fixtures(ctx, fixture)
    series = series_for_fixture(ctx.app.controller.model.images_dir(), fixture)
    if series is None:
        raise RuntimeError(f"No series for {fixture}")
    parent = ctx.app.dashboard or ctx.app
    view = show_series_view(parent, controller=ctx.app.controller, series_path=series, fonts=ctx.app.fonts)
    if view is None:
        raise RuntimeError("SeriesView failed")
    try:
        settle(view, max(ctx.settle_ms, 1000))
        return ShotResult(shot.id, "ok", series.name, ctx.grab(view, shot))
    finally:
        close_toplevel(view)


def shot_ai_batch_options(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    from anonymizer.view.ai.ai_batch_process_options_dialog import AiBatchProcessOptionsDialog

    if not ctx.imported_keys:
        _import_fixtures(ctx, "davidson_cxr", "CT_Head_With_Contrast", "us_rgb_single_frame")
    studies = study_tuples(ctx.app.controller.model.images_dir())
    if not studies:
        raise RuntimeError("No studies for batch options")
    parent = ctx.app.dashboard or ctx.app
    dlg = AiBatchProcessOptionsDialog(
        parent,
        project_dir=ctx.app.controller.model.storage_dir,
        images_dir=ctx.app.controller.model.images_dir(),
        studies=studies,
    )
    try:
        settle(dlg, max(ctx.settle_ms, 800))
        try:
            wait_mapped(dlg)
            dlg.update_idletasks()
        except Exception:
            pass
        return ShotResult(
            shot.id,
            "ok",
            f"{len(studies)} studies",
            ctx.grab(dlg, shot, settle_ms=max(ctx.settle_ms, 700)),
        )
    finally:
        close_toplevel(dlg)


def _prepare_send_view(ctx: CaptureContext):
    """Open Send/Export with several imported patients for staged screenshots."""
    _import_fixtures(ctx, "davidson_cxr", "CT_Head_With_Contrast", "us_rgb_single_frame")
    if ctx.app.export_view is not None:
        with contextlib.suppress(Exception):
            close_toplevel(ctx.app.export_view)
        ctx.app.export_view = None
    ctx.app.export()
    settle(ctx.app, max(ctx.settle_ms, 700))
    view = ctx.app.export_view
    if view is None:
        raise RuntimeError("ExportView/Send failed")
    settle(view, ctx.settle_ms)
    return view


def _stage_send_view(view: Any, stage: str) -> None:
    """Drive ExportView UI into initial / selection / sending / sent for docs shots."""
    from datetime import datetime

    from anonymizer.utils.translate import _

    children = list(view._tree.get_children(""))
    if not children:
        raise RuntimeError("Send view has no patients to stage")

    # Reset row values / tags before staging.
    for iid in children:
        values = list(view._tree.item(iid, "values") or [])
        while len(values) < 8:
            values.append("")
        values[5] = ""
        values[6] = ""
        values[7] = ""
        view._tree.item(iid, values=values, tags=())

    view._export_active = False
    view._enable_action_buttons()
    view._progressbar.set(0)
    view._status.configure(text=_("Processing") + " _ " + _("of") + " _ " + _("Patients"))
    view._tree.selection_set([])

    if stage in {"", "initial"}:
        return

    if stage == "selection":
        # Select first two patients when available so the highlight is obvious.
        selected = children[: min(2, len(children))]
        view._tree.selection_set(*selected)
        for iid in selected:
            view._tree.see(iid)
        return

    if stage == "sending":
        selected = children[: min(2, len(children))]
        view._tree.selection_set(*selected)
        view._patients_to_process = len(selected)
        view._patients_processed = 0
        view._patient_ids_to_export = list(selected)
        view._export_active = True
        view._disable_action_buttons()
        # First patient mid-flight: timestamp + partial Images Sent, still processing.
        first = selected[0]
        values = list(view._tree.item(first, "values") or [])
        while len(values) < 8:
            values.append("")
        total_files = int(values[4] or 0)
        values[5] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        values[6] = str(max(1, total_files // 2) if total_files else 1)
        values[7] = ""
        view._tree.item(first, values=values)
        view._patients_processed = 0
        view._update_export_progress()
        # Show progress part-way without completing.
        view._progressbar.set(0.35 if view._patients_to_process else 0.0)
        view._status.configure(
            text=(
                f"{_('Processing')} 0 {_('of')} {view._patients_to_process} {_('Patients')}"
            )
        )
        return

    if stage == "sent":
        # Same cohort as selection/sending — do not mark unselected patients complete.
        selected = children[: min(2, len(children))]
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for iid in selected:
            values = list(view._tree.item(iid, "values") or [])
            while len(values) < 8:
                values.append("")
            values[5] = stamp
            values[6] = str(values[4] or "0")
            values[7] = ""
            view._tree.item(iid, values=values, tags=("green",))
        view._tree.selection_set([])
        view._patients_to_process = len(selected)
        view._patients_processed = len(selected)
        view._patient_ids_to_export = []
        view._export_active = False
        view._enable_action_buttons()
        view._update_export_progress()
        return

    raise RuntimeError(f"Unknown Send recipe.stage={stage!r}")


def shot_send_view(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    recipe = shot.recipe or {}
    stage = str(recipe.get("stage") or "initial").strip().casefold()
    view = _prepare_send_view(ctx)
    try:
        _stage_send_view(view, stage)
        settle(view, max(ctx.settle_ms, 500))
        try:
            view.lift()
            view.attributes("-topmost", True)
        except Exception:
            pass
        dest = ctx.grab(view, shot, settle_ms=max(ctx.settle_ms, 600))
        try:
            view.attributes("-topmost", False)
        except Exception:
            pass
        return ShotResult(shot.id, "ok", f"Send:{stage}", dest)
    finally:
        close_toplevel(view)
        ctx.app.export_view = None


VIEW_DEMO_FIXTURES = ("davidson_cxr", "CT_Head_With_Contrast", "us_rgb_single_frame")
LOOKUP_FIXTURES = VIEW_DEMO_FIXTURES


def _open_clean_demo_project(ctx: CaptureContext, *, dirname: str) -> None:
    """Fresh project with only the three View demo fixtures (no synthetic leftovers)."""
    import shutil

    project_dir = ctx.work_dir / dirname
    if ctx.project_open:
        with contextlib.suppress(Exception):
            ctx.app.close_project()
        ctx.project_open = False
    if project_dir.exists():
        shutil.rmtree(project_dir)
    create_capture_project(project_dir)
    ctx.app.open_project(project_dir)
    settle(ctx.app, ctx.settle_ms)
    if not ctx.app.controller:
        raise RuntimeError(f"Failed to open demo project {dirname!r}")
    ctx.project_open = True
    ctx.imported_keys.clear()
    _import_fixtures(ctx, *VIEW_DEMO_FIXTURES)


def _open_patient_lookup_project(ctx: CaptureContext) -> None:
    """Dedicated project: davidson + CT head + US single-frame only (no synthetic)."""
    project_dir = ctx.work_dir / "project_patient_lookup"
    if (
        ctx.project_open
        and ctx.app.controller is not None
        and Path(str(ctx.app.controller.model.storage_dir)).resolve() == project_dir.resolve()
        and set(LOOKUP_FIXTURES).issubset(ctx.imported_keys)
    ):
        return
    _open_clean_demo_project(ctx, dirname="project_patient_lookup")
    ctx._lookup_processed = False  # type: ignore[attr-defined]


def _process_before_patient_lookup(ctx: CaptureContext) -> dict[str, object]:
    """Run Harmonize (CT head) and Remove Pixel PHI (davidson + US) before CSV export."""
    if getattr(ctx, "_lookup_processed", False):
        return dict(getattr(ctx, "_lookup_process_stats", {}) or {})

    from pathlib import Path as _Path

    from easyocr import Reader
    from pydicom import dcmread

    from anonymizer.controller.ai.harmonize.pipeline import (
        apply_harmonized_description,
        harmonize_and_apply_series,
    )
    from anonymizer.controller.ai.remove_pixel_phi import (
        OCR_LANGS,
        OCR_MODEL_DIR,
        apply_instance_pixel_phi_for_dcm,
        download_ocr_models,
        ocr_models_ready,
        remove_pixel_phi,
        _ocr_use_gpu,
    )

    controller = ctx.app.controller
    anon = controller.anonymizer.model
    images = controller.model.images_dir()
    project_dir = _Path(controller.model.storage_dir)
    stats: dict[str, object] = {
        "harmonize": "",
        "pixel_phi_series": 0,
        "pixel_phi_instances": 0,
    }

    brain = series_for_fixture(images, "CT_Head_With_Contrast")
    if brain is None:
        raise RuntimeError("CT head series missing for Patient Lookup processing")
    outcome = harmonize_and_apply_series(brain, anon_model=anon)
    stats["harmonize"] = f"{outcome.status}:{outcome.message}"
    if outcome.status == "failed":
        # Still mark processed so the CSV demo shows SeriesHarmonized=Yes if models unavailable.
        ds = dcmread(next(brain.glob("*.dcm")), stop_before_pixels=True, force=True)
        label = str(getattr(ds, "SeriesDescription", "") or "").strip() or "Brain Ax EarlyArt"
        if "BRAIN" in label.upper() or "EARLYART" in label.upper() or not label:
            label = "Brain Ax EarlyArt"
        apply_harmonized_description(brain, label, anon)
        stats["harmonize"] = f"fallback:{label} ({outcome.message})"

    if not ocr_models_ready():
        download_ocr_models()
    reader = Reader(
        lang_list=list(OCR_LANGS),
        model_storage_directory=str(OCR_MODEL_DIR),
        gpu=_ocr_use_gpu(),
    )
    pixel_series = 0
    pixel_instances = 0
    for fixture in ("davidson_cxr", "us_rgb_single_frame"):
        series = series_for_fixture(images, fixture)
        if series is None:
            raise RuntimeError(f"Series missing for Patient Lookup fixture {fixture!r}")
        dcms = sorted(series.glob("*.dcm"))
        if not dcms:
            raise RuntimeError(f"No DICOM files in {series}")
        series_uid = str(
            getattr(dcmread(dcms[0], stop_before_pixels=True, force=True), "SeriesInstanceUID", "") or ""
        )
        any_text = False
        for dcm_path in dcms:
            _modified, texts, _changed = remove_pixel_phi(
                dcm_path,
                reader,
                project_dir=project_dir,
            )
            if texts and apply_instance_pixel_phi_for_dcm(anon, dcm_path, texts):
                pixel_instances += 1
                any_text = True
        if series_uid:
            anon.set_series_pixel_phi_scanned(series_uid, scanned=True)
        if any_text:
            pixel_series += 1
    stats["pixel_phi_series"] = pixel_series
    stats["pixel_phi_instances"] = pixel_instances
    ctx._lookup_processed = True  # type: ignore[attr-defined]
    ctx._lookup_process_stats = stats  # type: ignore[attr-defined]
    return stats


def _render_patient_lookup_csv_preview(csv_path: Path, dest: Path, *, max_rows: int = 8) -> Path:
    """Render a docs-friendly preview of the Patient Lookup CSV (path + table)."""
    import csv

    from PIL import Image, ImageDraw, ImageFont

    from docs_help.platform.common import normalize_for_docs, save_docs_png

    with csv_path.open(newline="") as fh:
        reader = csv.reader(fh)
        rows = list(reader)
    if not rows:
        raise RuntimeError(f"Empty Patient Lookup CSV: {csv_path}")

    header = rows[0]
    body = rows[1 : 1 + max_rows]
    # Prefer columns that show Process outcomes (harmonize + pixel PHI text removed).
    prefer = [
        "PHI-PatientName",
        "ANON-PatientID",
        "Modality",
        "SeriesDescription",
        "SeriesHarmonized",
        "PixelPHIRemoved",
        "PixelPHI",
    ]
    indices = [header.index(name) for name in prefer if name in header]
    if not indices:
        indices = list(range(min(8, len(header))))

    def _cell(row: list[str], idx: int, *, col_name: str) -> str:
        if idx >= len(row):
            return ""
        text = str(row[idx] or "")
        limit = 48 if col_name == "PixelPHI" else 26
        return text if len(text) <= limit else text[: limit - 1] + "…"

    display_header = [header[i] for i in indices]
    display_rows = [
        [_cell(row, i, col_name=header[i]) for i in indices] for row in body
    ]

    def _font(size: int):
        for name in (
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/Library/Fonts/Arial.ttf",
        ):
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
        return ImageFont.load_default()

    title_font = _font(16)
    path_font = _font(12)
    cell_font = _font(11)
    pad = 18
    # Wider column for PixelPHI digest of removed text.
    col_widths = []
    for name in display_header:
        if name == "PixelPHI":
            col_widths.append(220)
        elif name in {"SeriesDescription", "PHI-PatientName"}:
            col_widths.append(140)
        else:
            col_widths.append(110)
    table_w = max(sum(col_widths), 900)
    row_h = 26
    table_h = row_h * (1 + len(display_rows))
    canvas_w = pad * 2 + table_w
    canvas_h = pad * 2 + 70 + table_h
    image = Image.new("RGB", (canvas_w, canvas_h), (246, 246, 246))
    draw = ImageDraw.Draw(image)
    draw.text((pad, pad), "Patient Lookup CSV", fill=(31, 106, 165), font=title_font)
    draw.text(
        (pad, pad + 26),
        f"…/private/phi_export/{csv_path.name}",
        fill=(60, 60, 60),
        font=path_font,
    )

    y0 = pad + 58
    x0 = pad
    draw.rectangle((x0, y0, x0 + table_w, y0 + row_h), fill=(31, 106, 165))
    x = x0
    for c, label in enumerate(display_header):
        draw.text((x + 6, y0 + 6), label, fill=(255, 255, 255), font=cell_font)
        x += col_widths[c]
    for r, row in enumerate(display_rows):
        y = y0 + row_h * (r + 1)
        fill = (255, 255, 255) if r % 2 == 0 else (236, 240, 245)
        draw.rectangle((x0, y, x0 + table_w, y + row_h), fill=fill, outline=(210, 210, 210))
        x = x0
        for c, label in enumerate(row):
            draw.text((x + 6, y + 6), label, fill=(40, 40, 40), font=cell_font)
            x += col_widths[c]
    draw.rectangle((x0, y0, x0 + table_w, y0 + table_h), outline=(180, 180, 180))

    image = normalize_for_docs(image)
    return save_docs_png(dest, image)


def shot_dataset_patient_lookup(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    """Dataset with Create Patient Lookup in view, or rendered CSV preview."""
    recipe = shot.recipe or {}
    mode = str(recipe.get("mode") or "button").strip().casefold()
    _open_patient_lookup_project(ctx)
    processed = _process_before_patient_lookup(ctx)
    logger.info("Patient Lookup pre-export processing: %s", processed)

    if mode == "csv":
        csv_path = ctx.app.controller.create_phi_csv()
        if isinstance(csv_path, str):
            raise RuntimeError(f"Create Patient Lookup failed: {csv_path}")
        import csv as csv_mod

        with Path(csv_path).open(newline="") as fh:
            rows = list(csv_mod.reader(fh))
        if len(rows) < 2:
            raise RuntimeError("Patient Lookup CSV has no data rows")
        header = rows[0]
        # Reject synthetic fixtures if they leaked into this project.
        try:
            name_i = header.index("PHI-PatientName")
            desc_i = header.index("SeriesDescription")
        except ValueError as exc:
            raise RuntimeError(f"Patient Lookup CSV missing identity columns: {exc}") from exc
        for row in rows[1:]:
            blob = f"{row[name_i] if len(row) > name_i else ''} {row[desc_i] if len(row) > desc_i else ''}".upper()
            if "SYNTHETIC" in blob or "PHANTOM" in blob:
                raise RuntimeError(f"Patient Lookup CSV contains synthetic data: {blob!r}")
        try:
            harm_i = header.index("SeriesHarmonized")
            rem_i = header.index("PixelPHIRemoved")
            phi_i = header.index("PixelPHI")
        except ValueError as exc:
            raise RuntimeError(f"Patient Lookup CSV missing AI columns: {exc}") from exc
        harm_yes = any(row[harm_i] == "Yes" for row in rows[1:] if len(row) > harm_i)
        rem_yes = any(row[rem_i] == "Yes" for row in rows[1:] if len(row) > rem_i)
        phi_text = any((row[phi_i] or "").strip() for row in rows[1:] if len(row) > phi_i)
        if not (harm_yes and rem_yes and phi_text):
            raise RuntimeError(
                f"Patient Lookup CSV missing processed AI columns "
                f"(harmonized={harm_yes}, pixel_removed={rem_yes}, pixel_text={phi_text}; "
                f"process={processed})"
            )
        dest = ctx.dest(shot)
        _render_patient_lookup_csv_preview(Path(csv_path), dest)
        return ShotResult(shot.id, "ok", f"csv:{Path(csv_path).name}:processed", dest)

    # Default: Dataset toolbar including Create Patient Lookup.
    ctx.app.view()
    settle(ctx.app, max(ctx.settle_ms, 800))
    view = ctx.app.dataset_view
    if view is None:
        raise RuntimeError("DatasetView failed")
    try:
        tree = view._tree
        view._update_tree_from_phi_index()
        settle(view, ctx.settle_ms)
        study_count = 0
        series_count = 0
        for iid in tree.get_children(""):
            study_count += 1
            tree.item(iid, open=True)
            for child in tree.get_children(iid):
                series_count += 1
        geometry = _fit_dataset_view_for_capture(view, study_count=study_count, series_count=series_count)
        try:
            view.geometry(geometry)
        except Exception:
            pass
        settle(view, max(ctx.settle_ms, 300))
        geometry = _fit_dataset_view_for_capture(view, study_count=study_count, series_count=series_count)
        try:
            view.geometry(geometry)
        except Exception:
            pass
        with contextlib.suppress(Exception):
            view._create_phi_button.focus_set()
        settle(view, max(ctx.settle_ms, 400))
        dest = ctx.grab(view, shot, settle_ms=max(ctx.settle_ms, 600), geometry=geometry)
        return ShotResult(shot.id, "ok", f"lookup_button:{study_count}studies@{geometry}", dest)
    finally:
        close_toplevel(view)
        ctx.app.dataset_view = None


def _series_view_for_fixture(ctx: CaptureContext, fixture: str):
    from anonymizer.view.series.series import show_series_view

    _import_fixtures(ctx, fixture)
    series = series_for_fixture(ctx.app.controller.model.images_dir(), fixture)
    if series is None:
        raise RuntimeError(f"No series for {fixture}")
    parent = ctx.app.dashboard or ctx.app
    view = show_series_view(parent, controller=ctx.app.controller, series_path=series, fonts=ctx.app.fonts)
    if view is None:
        raise RuntimeError("SeriesView failed")
    settle(view, max(ctx.settle_ms, 1200))
    return view, series


def shot_process_remove_pixel(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    """Series View OCR workflow: detect and/or remove burned-in text."""
    import time

    from anonymizer.controller.ai.remove_pixel_phi import (
        PixelPhiRemovalMode,
        normalize_pixel_phi_removal_mode,
        pixel_phi_removal_mode_option_label,
    )
    from anonymizer.controller.runner import OcrEditContext, edit_context_display_label
    from anonymizer.controller.series_overlay import UserRectangle

    fixture = _fixture_from_deps(shot.deps) or "davidson_cxr"
    recipe = shot.recipe or {}
    removal_mode = normalize_pixel_phi_removal_mode(
        recipe.get("removal_mode"),
        default=PixelPhiRemovalMode.BLACKOUT,
    )
    edit_ctx_raw = str(recipe.get("edit_context") or "frame").strip().casefold()
    edit_ctx = OcrEditContext.SERIES if edit_ctx_raw.startswith("series") else OcrEditContext.FRAME
    view, series = _series_view_for_fixture(ctx, fixture)
    try:
        # Default whitelist + Frame/Series context (keep orientation markers).
        try:
            label = edit_context_display_label(edit_ctx)
            if hasattr(view, "_edit_context_var"):
                view._edit_context_var.set(label)
            view.edit_context = edit_ctx
            if hasattr(view, "edit_context_change"):
                view.edit_context_change(label)
            if hasattr(view, "_load_whitelist_match_settings"):
                view._load_whitelist_match_settings()
            if hasattr(view, "remove_text_mode_var"):
                view.remove_text_mode_var.set(pixel_phi_removal_mode_option_label(removal_mode))
        except Exception as exc:
            logger.warning("Whitelist/frame setup: %s", exc)
        settle(view, ctx.settle_ms)

        actions = list(recipe.get("actions") or [])

        exclude_rect = recipe.get("exclude_rect")
        if exclude_rect is not None or "exclude_area" in actions:
            if not exclude_rect or len(exclude_rect) != 4:
                raise RuntimeError("exclude_area shots require recipe.exclude_rect: [x1, y1, x2, y2]")
            x1, y1, x2, y2 = (int(v) for v in exclude_rect)
            rect = UserRectangle(top_left=(x1, y1), bottom_right=(x2, y2))
            viewer = view.image_viewer
            frame_indices = range(viewer.num_images) if edit_ctx is OcrEditContext.SERIES else [viewer.current_image_index]
            for ndx in frame_indices:
                existing = list(viewer.get_exclude_rectangle_overlay_data(ndx) or [])
                viewer.set_exclude_rectangle_overlay_data(ndx, existing + [rect])
            try:
                viewer.refresh_current_image()
            except Exception:
                pass
            settle(view, max(ctx.settle_ms, 400))

        if "detect_text" in actions:
            work = getattr(view, "_ocr_work_state", None)
            if work is not None:
                with contextlib.suppress(Exception):
                    work.prepare_job()
            view.detect_text_button_clicked()
            deadline = time.monotonic() + 180.0
            saw_running = False
            while time.monotonic() < deadline:
                settle(ctx.app, 150)
                work = getattr(view, "_ocr_work_state", None)
                if work is not None:
                    if work.error:
                        raise RuntimeError(f"Detect Text failed: {work.error}")
                    # Job may set done briefly, then on_done resets WorkState.
                    if bool(work.done):
                        break
                    if (work.status or "").strip() or work.fraction > 0:
                        saw_running = True
                ndx = view.image_viewer.current_image_index
                ocr = view.image_viewer.overlay_data.get(ndx)
                texts = list(getattr(ocr, "ocr_texts", []) or []) if ocr is not None else []
                # Overlays applied after finish (WorkState often already reset).
                if texts and saw_running:
                    break
                status_msg = ""
                try:
                    if hasattr(view, "_status_label"):
                        status_msg = str(view._status_label.cget("text") or "")
                except Exception:
                    status_msg = ""
                if "detection complete" in status_msg.casefold():
                    break
            else:
                raise RuntimeError("Timed out waiting for Detect Text")
            settle(view, max(ctx.settle_ms, 700))
            try:
                view._refresh_ocr_toolbar_buttons()
            except Exception:
                pass
            # Detect-only shots must show green rectangles (result), not the busy status.
            if "remove_text" not in actions:
                ndx = view.image_viewer.current_image_index
                ocr = view.image_viewer.overlay_data.get(ndx)
                texts = list(getattr(ocr, "ocr_texts", []) or []) if ocr is not None else []
                if not texts:
                    raise RuntimeError("Detect Text shot expected green OCR overlays, found none")
                settle(view, 500)

        if "remove_text" in actions:
            ndx = view.image_viewer.current_image_index
            ocr = view.image_viewer.overlay_data.get(ndx)
            texts = list(getattr(ocr, "ocr_texts", []) or []) if ocr is not None else []
            if not texts:
                raise RuntimeError("Remove Text shot requires Detect Text overlays first")
            # Re-assert removal mode in case Detect refreshed toolbar widgets.
            if hasattr(view, "remove_text_mode_var"):
                view.remove_text_mode_var.set(pixel_phi_removal_mode_option_label(removal_mode))
            view.remove_text_button_clicked()
            settle(view, max(ctx.settle_ms, 800))
            ocr_after = view.image_viewer.overlay_data.get(ndx)
            remaining = list(getattr(ocr_after, "ocr_texts", []) or []) if ocr_after is not None else []
            if remaining:
                raise RuntimeError(f"Remove Text left {len(remaining)} OCR overlay(s)")
            try:
                view.image_viewer.refresh_current_image()
            except Exception:
                pass
            settle(view, 500)

        try:
            view.lift()
            view.attributes("-topmost", True)
        except Exception:
            pass
        # Multi-frame US windows often return black Screen Recording frames; shrink first.
        try:
            if int(getattr(view.image_viewer, "num_images", 1) or 1) > 1:
                view.geometry("1280x860+24+40")
                settle(view, max(ctx.settle_ms, 500))
        except Exception:
            pass
        try:
            dest = ctx.grab(view, shot, settle_ms=max(ctx.settle_ms, 700))
        except RuntimeError as exc:
            msg = str(exc).casefold()
            if "blank" in msg or "screen capture" in msg:
                logger.warning(
                    "Screen grab failed for %s; using off-screen Series View export: %s",
                    shot.id,
                    exc,
                )
                from docs_help.series_view_export import export_series_view_docs_shot

                dest = export_series_view_docs_shot(view, ctx.dest(shot))
            else:
                raise
        try:
            view.attributes("-topmost", False)
        except Exception:
            pass
        return ShotResult(
            shot.id,
            "ok",
            f"{fixture}:{actions}:mode={removal_mode.value}:ctx={edit_ctx.value}",
            dest,
        )
    finally:
        close_toplevel(view)


def shot_process_harmonize_description(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    """Series View (CT head) above completed Harmonize Description results."""
    from docs_help.harmonize import (
        BrainPromptPolicy,
        close_harmonize_session,
        grab_series_with_overlays,
        layout_series_above_harmonize,
        prepare_series_for_harmonize,
        run_harmonize_to_results,
    )

    fixture = _fixture_from_deps(shot.deps) or "CT_Head_With_Contrast"
    session = prepare_series_for_harmonize(
        ctx,
        fixture,
        import_fixtures=_import_fixtures,
        clear_cache=True,
    )
    try:
        hv = run_harmonize_to_results(session, policy=BrainPromptPolicy.AUTO_NO)
        layout_series_above_harmonize(session.series_view, hv, peek_px=240)
        dest = grab_series_with_overlays(ctx, session.series_view, hv, shot=shot)
        return ShotResult(shot.id, "ok", f"{fixture}:results+series", dest)
    finally:
        close_harmonize_session(session)


def shot_process_harmonize_brain_prompt(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    """Harmonize Description dialog + brain-structures Yes/No (no Series View)."""
    from docs_help.harmonize import (
        capture_brain_prompt_over_harmonize,
        close_harmonize_session,
        ensure_brain_structures_models,
        prepare_series_for_harmonize,
    )

    fixture = _fixture_from_deps(shot.deps) or "CT_Head_With_Contrast"
    # Prefer live prompt when models exist; otherwise stand-in copy is used.
    try:
        ensure_brain_structures_models()
    except Exception as exc:
        logger.warning("Brain models for prompt shot: %s", exc)
    session = prepare_series_for_harmonize(
        ctx,
        fixture,
        import_fixtures=_import_fixtures,
        clear_cache=True,
    )
    try:
        dest = capture_brain_prompt_over_harmonize(ctx, session, shot, answer=False)
        return ShotResult(shot.id, "ok", f"{fixture}:brain_prompt", dest)
    finally:
        close_harmonize_session(session)


def shot_process_harmonize_segmented_series(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    """Series View after brain Harmonize: detailed brain-structure latches on middle slice.

    Runs Harmonize+brain in a Tk-free precompute step first (TotalSegmentator + Tk
    segfaults on this host when started from Series View), then opens Series View
    on the cached masks for the help screenshot. Does not latch whole-brain or skull.
    """
    import gc

    from docs_help.harmonize import (
        clear_series_analysis_cache,
        goto_middle_slice,
        grab_series_with_overlays,
        latch_brain_and_detail_overlays,
        open_series_view,
        precompute_brain_harmonize_cache,
        prepare_series_view_for_grab,
        require_brain_structure_latches,
        series_has_brain_structure_cache,
    )
    from docs_help.project_setup import series_for_fixture

    fixture = _fixture_from_deps(shot.deps) or "CT_Head_With_Contrast"
    _import_fixtures(ctx, fixture)
    series_path = series_for_fixture(ctx.app.controller.model.images_dir(), fixture)
    if series_path is None:
        raise RuntimeError(f"No series for fixture {fixture!r}")

    series_view = None
    try:
        if series_has_brain_structure_cache(series_path):
            logger.info("Reusing existing brain-structure cache under %s", series_path)
        else:
            series_view = open_series_view(ctx, series_path)
            clear_series_analysis_cache(series_view)
            close_toplevel(series_view)
            series_view = None
            precompute_brain_harmonize_cache(
                series_path,
                anon_model=ctx.app.controller.anonymizer.model,
            )
            try:
                from anonymizer.controller.ai.tseg.model_cache import clear_predictor_cache

                clear_predictor_cache()
            except Exception as exc:
                logger.warning("clear_predictor_cache: %s", exc)
            gc.collect()

        series_view = open_series_view(ctx, series_path)
        settle(series_view, max(ctx.settle_ms, 1200))
        try:
            series_view._refresh_analysis_cache_ui()
        except Exception as exc:
            logger.warning("Series View refresh after precompute: %s", exc)
        detail = require_brain_structure_latches(series_view, min_count=8)
        mid = goto_middle_slice(series_view)
        names = latch_brain_and_detail_overlays(series_view)
        if "brain" in names or "skull" in names:
            raise RuntimeError(f"SegmentedSeries must not latch brain/skull; got {names}")
        prepare_series_view_for_grab(series_view, settle_ms=1200)
        # Always capture the live Series View window (never the off-screen mock).
        dest = grab_series_with_overlays(ctx, series_view, shot=shot)
        try:
            series_view.attributes("-topmost", False)
        except Exception:
            pass
        return ShotResult(
            shot.id,
            "ok",
            f"{fixture}:mid={mid}:segs={len(names)}:brain_detail={len(detail)}",
            dest,
        )
    finally:
        if series_view is not None:
            close_toplevel(series_view)


def shot_process_face_blur(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    """Face Blur review dialog after Gaussian preview completes (QA + Save enabled)."""
    import time

    import numpy as np

    from anonymizer.controller.ai.blur_face.pipeline import FaceBlurMode
    from anonymizer.view.ai.face_blur_review_dialog import FaceBlurReviewDialog

    fixture = _fixture_from_deps(shot.deps) or "CT_Head_With_Contrast"
    _import_fixtures(ctx, fixture)
    series = series_for_fixture(ctx.app.controller.model.images_dir(), fixture)
    if series is None:
        raise RuntimeError(f"No series for {fixture}")
    parent = ctx.app.dashboard or ctx.app
    dlg = FaceBlurReviewDialog(
        parent,
        anon_model=ctx.app.controller.anonymizer.model,
        series_path=series,
        blur_mode=FaceBlurMode.GAUSSIAN,
    )
    try:
        # Wait through loading shell + blur worker until review UI is ready.
        deadline = time.monotonic() + 900.0
        while time.monotonic() < deadline:
            settle(ctx.app, 200)
            try:
                if not dlg.winfo_exists():
                    raise RuntimeError("Face blur dialog closed before review was ready")
            except Exception as exc:
                if "closed before" in str(exc):
                    raise
                break
            preview = getattr(dlg, "_preview", None)
            if preview is not None and not getattr(dlg, "_blur_running", True) and not getattr(dlg, "_loading", True):
                break
        else:
            raise RuntimeError("Timed out waiting for Face Blur review (QA) to finish")

        viewer = dlg.image_viewer
        preview = dlg._preview
        best = max(0, int(viewer.num_images) // 2)
        mask = getattr(preview, "mask", None)
        if mask is not None and getattr(mask, "ndim", 0) == 3 and mask.shape[0] > 0:
            # Prefer the slice with the largest face-mask area so the green
            # overlay is clearly visible in the help screenshot.
            voxel_counts = [int(np.count_nonzero(mask[i])) for i in range(mask.shape[0])]
            max_voxels = max(voxel_counts) if voxel_counts else 0
            if max_voxels > 0:
                best = int(max(range(len(voxel_counts)), key=voxel_counts.__getitem__))
                logger.info(
                    "Face blur shot: slice %s/%s with %s face-mask voxels (max)",
                    best + 1,
                    mask.shape[0],
                    max_voxels,
                )
        viewer.load_and_display_image(best)
        settle(dlg, max(ctx.settle_ms, 900))
        # Re-apply overlays after slice change so green face contour is painted.
        try:
            ensure = getattr(viewer, "_ensure_overlays_for_frame", None)
            if callable(ensure):
                ensure(best)
            viewer.load_and_display_image(best)
        except Exception as exc:
            logger.warning("Face blur overlay refresh: %s", exc)
        settle(dlg, 500)
        try:
            dlg.lift()
            dlg.attributes("-topmost", True)
        except Exception:
            pass
        settle(dlg, 400)
        dest = ctx.grab(dlg, shot)
        try:
            dlg.attributes("-topmost", False)
        except Exception:
            pass
        qa = getattr(getattr(preview, "qa_stats", None), "passed", None)
        return ShotResult(shot.id, "ok", f"gaussian:slice={best}:qa={qa}", dest)
    finally:
        close_toplevel(dlg)


SHOT_HANDLERS: dict[str, Callable[[CaptureContext, ShotSpec], ShotResult]] = {
    "Welcome": shot_welcome,
    "NewProjectSettings": shot_new_project_settings,
    "LocalServer": shot_local_server,
    "QueryServer": shot_query_server,
    "ExportServer": shot_export_server,
    "AWSCognito": shot_aws,
    "NetworkTimeouts": shot_network_timeouts,
    "Modalities": shot_modalities,
    "StorageClasses": shot_storage_classes,
    "TransferSyntaxes": shot_transfer_syntaxes,
    "LookupTable": shot_lookup_table,
    "LoggingLevels": shot_logging_levels,
    "Dashboard": shot_dashboard,
    "AiFeaturesSetup": shot_ai_features,
    "ImportFiles_Menu": shot_import_davidson_menu,
    "ImportDirectory_Chooser": shot_import_directory_chooser,
    "ImportDavidson_Done": shot_import_davidson_done,
    "ImportDirectory_Log": shot_import_directory_log,
    "ImportFilesDialog": shot_import_files,
    "QueryRetrieve_Ready": shot_query_retrieve_ready,
    "OrthancCT_Query": shot_orthanc_ct_query,
    "OrthancCT_Importing": shot_orthanc_ct_importing,
    "OrthancCT_Imported": shot_orthanc_ct_imported,
    "QueryRetrieveImport": shot_query,
    "Dataset": shot_dataset,
    "Dataset_EditDescription": shot_dataset_edit_description,
    "Dataset_EditStudyDescription": shot_dataset_edit_study_description,
    "Dataset_CreatePatientLookup": shot_dataset_patient_lookup,
    "Dataset_PatientLookup_CSV": shot_dataset_patient_lookup,
    "ViewProjections": shot_view_projections,
    "ViewProjections_Multi": shot_view_projections_multi,
    "SeriesView_Review": shot_series_review,
    "AiBatchOptions": shot_ai_batch_options,
    "SendView_Initial": shot_send_view,
    "SendView_Selection": shot_send_view,
    "SendView_Sending": shot_send_view,
    "SendView_Sent": shot_send_view,
    "SendView": shot_send_view,
    "Process_RemovePixel_Whitelist": shot_process_remove_pixel,
    "Process_RemovePixel_Detect": shot_process_remove_pixel,
    "Process_RemovePixel_Remove": shot_process_remove_pixel,
    "Process_RemovePixel_US_Detect": shot_process_remove_pixel,
    "Process_RemovePixel_US_Blend": shot_process_remove_pixel,
    "Process_RemovePixel_US_Exclude_Panel": shot_process_remove_pixel,
    "Process_RemovePixel_US_Exclude_Detect": shot_process_remove_pixel,
    "Process_Harmonize_Description": shot_process_harmonize_description,
    "Process_Harmonize_BrainPrompt": shot_process_harmonize_brain_prompt,
    "Process_Harmonize_SegmentedSeries": shot_process_harmonize_segmented_series,
    "Process_FaceBlur_Gaussian": shot_process_face_blur,
}

