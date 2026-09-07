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
    """File menu stand-in (Import Files / Import Directory) — reliable on macOS."""
    import customtkinter as ctk
    from anonymizer.utils.translate import _

    _ensure_project(ctx)
    settle(ctx.app, ctx.settle_ms)
    x = int(ctx.app.winfo_rootx()) + 48
    y = int(ctx.app.winfo_rooty()) + 64
    standin = ctk.CTkToplevel(ctx.app)
    try:
        standin.title("")
        standin.geometry(f"240x168+{x}+{y}")
        standin.resizable(False, False)
        standin.attributes("-topmost", True)
        frame = ctk.CTkFrame(standin, corner_radius=8)
        frame.pack(fill="both", expand=True, padx=4, pady=4)
        for i, label in enumerate(
            (_("Import Files"), _("Import Directory"), None, _("Clone Project"), _("Close Project"))
        ):
            if label is None:
                ctk.CTkFrame(frame, height=1, fg_color=("gray70", "gray40")).pack(fill="x", padx=8, pady=4)
                continue
            btn = ctk.CTkButton(
                frame,
                text=label,
                anchor="w",
                fg_color=("#3a7ebf", "#1f538d") if i == 0 else "transparent",
                text_color=("#DCE4EE", "#DCE4EE") if i == 0 else ("gray14", "gray84"),
                hover=False,
                height=28,
            )
            btn.pack(fill="x", padx=4, pady=1)
        settle(standin, max(ctx.settle_ms, 500))
        return ShotResult(shot.id, "ok", "File menu stand-in", ctx.grab(standin, shot))
    finally:
        if standin.winfo_exists():
            close_toplevel(standin)


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
        dest = ctx.grab(dlg, shot, settle_ms=max(ctx.settle_ms, 500))
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
    paths = collect_import_paths("davidson_cxr", "Brain_Ax_EarlyArt", "chest")
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
        dest = ctx.grab(dlg, shot, settle_ms=max(ctx.settle_ms, 500))
        ctx.imported_keys.update({"davidson_cxr", "Brain_Ax_EarlyArt", "chest", "test_dcm_files"})
        return ShotResult(shot.id, "ok", f"directory log {len(sample)} files", dest)
    finally:
        if dlg.winfo_exists():
            close_toplevel(dlg)


def shot_query_retrieve_ready(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    """Dashboard Search → Query window with all controls visible (no results yet)."""
    _ensure_project(ctx)
    assert_orthanc_reachable(ctx.app.controller)
    seed_orthanc_if_empty(ctx.app.controller, collect_import_paths("Brain_Ax_EarlyArt", "chest"))

    ctx.app.query_retrieve()
    settle(ctx.app, ctx.settle_ms)
    view = ctx.app.query_view
    if view is None or not view.winfo_exists():
        raise RuntimeError("QueryView failed")
    try:
        view.geometry("1280x720")
        view.lift()
        view.focus_force()
    except Exception:
        pass
    settle(view, max(ctx.settle_ms, 600))
    dest = ctx.grab(view, shot, geometry="1280x720", settle_ms=max(ctx.settle_ms, 600))
    close_toplevel(view)
    with contextlib.suppress(Exception):
        ctx.app.query_view = None
    return ShotResult(shot.id, "ok", "QueryRetrieve ready", dest)


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
    ct_paths = collect_import_paths("Brain_Ax_EarlyArt", "chest")
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
        view.geometry("1280x720")
        view.lift()
        view.focus_force()
    except Exception:
        pass
    settle(view, ctx.settle_ms)

    if hasattr(view, "_modality_var"):
        view._modality_var.set("CT")
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

    query_shot = _shot_by_id(ctx, "OrthancCT_Query") or primary
    query_dest = ctx.grab(view, query_shot, geometry="1280x720", settle_ms=max(ctx.settle_ms, 600))

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
                        settle(widget, 400)
                        ctx.grab(widget, importing_shot, settle_ms=400)
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
    try:
        view.geometry("1280x720")
        view.lift()
        view.focus_force()
    except Exception:
        pass

    imported_shot = _shot_by_id(ctx, "OrthancCT_Imported")
    if imported_shot is not None:
        ctx.grab(view, imported_shot, geometry="1280x720", settle_ms=max(ctx.settle_ms, 600))
        ctx._orthanc_imported_captured = True  # type: ignore[attr-defined]

    n = len(list(view._query_results.get_children()))
    return ShotResult(
        primary.id,
        "ok",
        f"Doe^Archibald CT workflow studies={n} scp_port={ctx.app.controller.model.scp.port}",
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
    """Shrink Dataset so the tree fills the window (no large empty grey pane).

    Treeview defaults to ``height=30`` rows; for help shots we size to visible
    study+series rows and drop row weight so the window hugs content.
    """
    visible = max(1, int(study_count) + int(series_count))
    # One spare row + heading; cap so huge imports stay readable on screen.
    tree_rows = min(max(visible + 1, 6), 16)
    try:
        view._tree.configure(height=tree_rows)
    except Exception:
        pass
    try:
        # Prevent the index frame from expanding into empty vertical space.
        view.grid_rowconfigure(0, weight=0)
        view._index_frame.grid_rowconfigure(0, weight=0)
    except Exception:
        pass
    try:
        view.update_idletasks()
        view.update()
    except Exception:
        pass
    try:
        req_w = int(view.winfo_reqwidth())
        req_h = int(view.winfo_reqheight())
    except Exception:
        req_w, req_h = 1100, 420
    # Wide enough for AI status columns; height from content only.
    width = max(980, min(req_w + 20, 1280))
    height = max(280, min(req_h + 12, 720))
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
    # Import several fixture studies so the Study/Series tree has a countable list.
    _import_fixtures(
        ctx,
        "davidson_cxr",
        "Brain_Ax_EarlyArt",
        "chest",
        "head",
        "abdomen",
    )
    _ensure_project(ctx)
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
    except Exception as exc:
        logger.warning("Dataset tree expand: %s", exc)
    settle(view, max(ctx.settle_ms, 600))
    if study_count < 2:
        raise RuntimeError(f"Dataset tree needs ≥2 studies for help screenshots; got {study_count}")
    geometry = _fit_dataset_view_for_capture(view, study_count=study_count, series_count=series_count)
    settle(view, max(ctx.settle_ms, 400))
    dest = ctx.grab(view, shot, geometry=geometry, settle_ms=max(ctx.settle_ms, 700))
    return ShotResult(shot.id, "ok", f"{study_count} studies / {series_count} series @ {geometry}", dest)


def shot_view_projections(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    """Dataset → select Brain_Ax study → View Projections window with thumbnails."""
    from anonymizer.view.series.projection import ProjectionView

    _import_fixtures(ctx, "davidson_cxr", "Brain_Ax_EarlyArt", "chest")
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

    # Prefer multi-slice head CT so projection tiles are meaningful.
    # Study label is often "CT Head W contrast"; series may say "Brain Ax EarlyA".
    _select_dataset_study(view, "Brain", "EarlyArt", "EarlyA", "Head W", "CT Head")
    settle(view, max(ctx.settle_ms, 300))
    view._view_projections_button_pressed()
    settle(ctx.app, max(ctx.settle_ms, 800))

    proj = None
    for _ in range(40):
        for child in list(view.winfo_children()) + list(ctx.app.winfo_children()):
            if isinstance(child, ProjectionView):
                try:
                    if child.winfo_exists() and child.winfo_viewable():
                        proj = child
                        break
                except Exception:
                    continue
        if proj is not None:
            break
        settle(ctx.app, 100)
    if proj is None:
        # Fallback: open directly from selected records.
        records = view._selected_study_records()
        if not records:
            raise RuntimeError("View Projections: no study selected")
        proj = ProjectionView(
            view,
            controller=ctx.app.controller,
            base_dir=ctx.app.controller.model.images_dir(),
            phi_records=records,
            fonts=view._fonts,
        )
        settle(proj, max(ctx.settle_ms, 800))

    try:
        settle(proj, max(ctx.settle_ms, 1000))
        # Medium tiles read better in help than the default Small size.
        try:
            if hasattr(proj, "_image_size_button"):
                proj._image_size_button.set("M")
                proj._update_image_size("M")
                settle(proj, max(ctx.settle_ms, 600))
        except Exception as exc:
            logger.warning("ViewProjections size M: %s", exc)
        try:
            wait_mapped(proj)
        except Exception:
            pass
        dest = ctx.grab(proj, shot, settle_ms=max(ctx.settle_ms, 700))
        return ShotResult(shot.id, "ok", proj.title(), dest)
    finally:
        close_toplevel(proj)


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
        _import_fixtures(ctx, "davidson_cxr", "Brain_Ax_EarlyArt", "chest")
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


def shot_send_view(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    if not ctx.imported_keys:
        _import_fixtures(ctx, "davidson_cxr")
    ctx.app.export()
    settle(ctx.app, ctx.settle_ms)
    view = ctx.app.export_view
    if view is None:
        raise RuntimeError("ExportView/Send failed")
    return ShotResult(shot.id, "ok", "SendView", ctx.grab(view, shot))


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

    fixture = _fixture_from_deps(shot.deps) or "davidson_cxr"
    recipe = shot.recipe or {}
    removal_mode = normalize_pixel_phi_removal_mode(
        recipe.get("removal_mode"),
        default=PixelPhiRemovalMode.BLACKOUT,
    )
    view, series = _series_view_for_fixture(ctx, fixture)
    try:
        # Default whitelist + Frame context (keep orientation markers).
        try:
            if hasattr(view, "_edit_context_var"):
                view._edit_context_var.set(edit_context_display_label(OcrEditContext.FRAME))
            view.edit_context = OcrEditContext.FRAME
            if hasattr(view, "edit_context_change"):
                view.edit_context_change(edit_context_display_label(OcrEditContext.FRAME))
            if hasattr(view, "_load_whitelist_match_settings"):
                view._load_whitelist_match_settings()
            if hasattr(view, "remove_text_mode_var"):
                view.remove_text_mode_var.set(pixel_phi_removal_mode_option_label(removal_mode))
        except Exception as exc:
            logger.warning("Whitelist/frame setup: %s", exc)
        settle(view, ctx.settle_ms)

        actions = list(recipe.get("actions") or [])

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
        dest = ctx.grab(view, shot, settle_ms=max(ctx.settle_ms, 700))
        try:
            view.attributes("-topmost", False)
        except Exception:
            pass
        return ShotResult(
            shot.id,
            "ok",
            f"{fixture}:{actions}:mode={removal_mode.value}",
            dest,
        )
    finally:
        close_toplevel(view)


def shot_process_harmonize_description(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    """Series View (Brain_Ax) above completed Harmonize Description results."""
    from docs_help.harmonize import (
        BrainPromptPolicy,
        close_harmonize_session,
        grab_series_with_overlays,
        layout_series_above_harmonize,
        prepare_series_for_harmonize,
        run_harmonize_to_results,
    )

    fixture = _fixture_from_deps(shot.deps) or "Brain_Ax_EarlyArt"
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

    fixture = _fixture_from_deps(shot.deps) or "Brain_Ax_EarlyArt"
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

    fixture = _fixture_from_deps(shot.deps) or "Brain_Ax_EarlyArt"
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

    fixture = _fixture_from_deps(shot.deps) or "Brain_Ax_EarlyArt"
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
    "ImportDavidson_Done": shot_import_davidson_done,
    "ImportDirectory_Log": shot_import_directory_log,
    "ImportFilesDialog": shot_import_files,
    "QueryRetrieve_Ready": shot_query_retrieve_ready,
    "OrthancCT_Query": shot_orthanc_ct_query,
    "OrthancCT_Importing": shot_orthanc_ct_importing,
    "OrthancCT_Imported": shot_orthanc_ct_imported,
    "QueryRetrieveImport": shot_query,
    "Dataset": shot_dataset,
    "ViewProjections": shot_view_projections,
    "SeriesView_Review": shot_series_review,
    "AiBatchOptions": shot_ai_batch_options,
    "SendView": shot_send_view,
    "Process_RemovePixel_Whitelist": shot_process_remove_pixel,
    "Process_RemovePixel_Detect": shot_process_remove_pixel,
    "Process_RemovePixel_Remove": shot_process_remove_pixel,
    "Process_RemovePixel_US_Detect": shot_process_remove_pixel,
    "Process_RemovePixel_US_Blend": shot_process_remove_pixel,
    "Process_Harmonize_Description": shot_process_harmonize_description,
    "Process_Harmonize_BrainPrompt": shot_process_harmonize_brain_prompt,
    "Process_Harmonize_SegmentedSeries": shot_process_harmonize_segmented_series,
    "Process_FaceBlur_Gaussian": shot_process_face_blur,
}

