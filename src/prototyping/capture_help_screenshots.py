#!/usr/bin/env python3
"""Capture V19 help screenshots into numbered workflow ``shots/`` folders.

Reads ``docs/screenshots-manifest.yaml``. Re-run per language — do not pixel-translate PNGs.

::

    uv run python src/prototyping/capture_help_screenshots.py --language en_US
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
import shutil
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "anonymizer"
CAPTURE_WORK = REPO_ROOT / "docs" / ".capture_work"

_PROTOTYPING = REPO_ROOT / "src" / "prototyping"
if str(_PROTOTYPING) not in sys.path:
    sys.path.insert(0, str(_PROTOTYPING))

from docs_capture.grab import (  # noqa: E402
    close_toplevel,
    grab_widget,
    screen_capture_available,
    settle,
    wait_mapped,
)
from docs_capture.manifest import ShotSpec, load_manifest  # noqa: E402
from docs_capture.orthanc import (  # noqa: E402
    assert_orthanc_reachable,
    find_any_studies,
    seed_orthanc_ct,
    seed_orthanc_if_empty,
)
from docs_capture.project_setup import (  # noqa: E402
    CTP_LOOKUP_PROPERTIES,
    collect_import_paths,
    create_capture_project,
    series_for_fixture,
    study_tuples,
)

logger = logging.getLogger("capture_help_screenshots")


@dataclass
class ShotResult:
    shot_id: str
    status: str
    detail: str = ""
    path: Path | None = None


@dataclass
class CaptureContext:
    app: Any
    manifest: Any
    language: str
    settle_ms: int
    allow_placeholder: bool = False
    work_dir: Path = field(default_factory=Path)
    imported_keys: set[str] = field(default_factory=set)
    project_open: bool = False
    results: list[ShotResult] = field(default_factory=list)

    def dest(self, shot: ShotSpec) -> Path:
        return self.manifest.output_path(self.language, shot)

    def grab(
        self,
        widget: Any,
        shot: ShotSpec,
        *,
        settle_ms: int | None = None,
        geometry: str | None = None,
    ) -> Path:
        return grab_widget(
            widget,
            self.dest(shot),
            settle_ms=self.settle_ms if settle_ms is None else settle_ms,
            allow_placeholder=self.allow_placeholder,
            shot_id=shot.id,
            geometry=geometry,
        )


def _prepare_environment(work_dir: Path) -> Path:
    os.chdir(PACKAGE_DIR)
    logs_dir = work_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def _record(ctx: CaptureContext, result: ShotResult) -> None:
    ctx.results.append(result)
    mark = {"ok": "OK", "soft_fail": "SOFT", "hard_fail": "FAIL", "skipped": "SKIP"}.get(result.status, result.status)
    where = f" → {result.path}" if result.path else ""
    print(f"[{mark}] {result.shot_id}: {result.detail}{where}")


def _ensure_project(ctx: CaptureContext) -> None:
    if ctx.project_open:
        return
    project_dir = create_capture_project(ctx.work_dir / "project")
    ctx.app.open_project(project_dir)
    settle(ctx.app, ctx.settle_ms)
    if not ctx.app.controller:
        raise RuntimeError("ProjectController not created after open_project")
    ctx.project_open = True


def _import_fixtures(ctx: CaptureContext, *keys: str) -> None:
    _ensure_project(ctx)
    needed = [k for k in keys if k not in ctx.imported_keys]
    if not needed:
        return
    paths = collect_import_paths(*needed)
    anon = ctx.app.controller.anonymizer
    errors = 0
    for path in paths:
        err, _ds = anon.anonymize_file(Path(path))
        if err:
            errors += 1
            logger.warning("Import error %s: %s", path, err)
    settle(ctx.app, ctx.settle_ms)
    ctx.imported_keys.update(needed)
    if errors and errors == len(paths):
        raise RuntimeError(f"All {len(paths)} import(s) failed for {needed}")


def _fixture_from_deps(deps: tuple[str, ...]) -> str | None:
    for dep in deps:
        if dep.startswith("fixture:"):
            return dep.split(":", 1)[1]
    return None


def _open_settings(ctx: CaptureContext, *, new_model: bool = False):
    from anonymizer.model.project import ProjectModel
    from anonymizer.utils.translate import _
    from anonymizer.view.settings.settings_dialog import SettingsDialog

    if new_model:
        model = ProjectModel()
        model.storage_dir = ctx.work_dir / "settings_preview_storage"
        model.storage_dir.mkdir(parents=True, exist_ok=True)
        return SettingsDialog(parent=ctx.app, model=model, new_model=True, title=_("New Project Settings"))
    _ensure_project(ctx)
    return SettingsDialog(
        parent=ctx.app,
        model=ctx.app.controller.model,
        new_model=False,
        project_controller=ctx.app.controller,
    )


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

    from docs_capture.grab import _display_scale, _normalize_for_docs, _to_logical_size, _trim_transparent

    if not isinstance(image, Image.Image):
        raise TypeError("expected PIL Image")
    image = _trim_transparent(image.convert("RGBA"))
    image = _to_logical_size(image, _display_scale(widget))
    image = _normalize_for_docs(image)
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, format="PNG")
    return dest


def shot_import_davidson_menu(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    """Floating File menu (Import Files / Import Directory) via tk_popup."""
    import customtkinter as ctk
    from anonymizer.utils.translate import _
    from PIL import Image, ImageGrab

    from docs_capture.macos_window import list_cg_windows, screencapture_window

    _ensure_project(ctx)
    settle(ctx.app, ctx.settle_ms)
    file_menu = _project_file_menu(ctx.app)
    dest = ctx.dest(shot)
    standin = None
    try:
        x = int(ctx.app.winfo_rootx()) + 48
        y = int(ctx.app.winfo_rooty()) + 64
        # tk_popup shows a real floating menu; .post often no-ops on macOS menubar menus.
        with contextlib.suppress(Exception):
            file_menu.tk_popup(x, y)
        settle(ctx.app, max(ctx.settle_ms, 800))

        image = None
        pid = os.getpid()
        if sys.platform == "darwin":
            best = None
            best_area = None
            for win in list_cg_windows():
                if int(win.get("pid") or -1) != pid:
                    continue
                ww, wh = float(win.get("w") or 0), float(win.get("h") or 0)
                if ww < 120 or wh < 90 or ww > 420 or wh > 360:
                    continue
                wx, wy = float(win.get("x") or 0), float(win.get("y") or 0)
                if abs(wx - x) > 160 or abs(wy - y) > 160:
                    continue
                area = ww * wh
                if best is None or area < best_area:
                    best, best_area = win, area
            if best is not None:
                tmp = dest.with_suffix(".tmp.png")
                try:
                    screencapture_window(int(best["id"]), tmp, shadow=False)
                    image = Image.open(tmp)
                    image.load()
                finally:
                    tmp.unlink(missing_ok=True)

        if image is None:
            # Reliable stand-in: small File menu popup (macOS menubar menus often can't be grabbed).
            standin = ctk.CTkToplevel(ctx.app)
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
                    ctk.CTkFrame(frame, height=1, fg_color=("gray70", "gray40")).pack(
                        fill="x", padx=8, pady=4
                    )
                    continue
                btn = ctk.CTkButton(
                    frame,
                    text=label,
                    anchor="w",
                    fg_color=("#3a7ebf", "#1f538d") if i == 1 else "transparent",
                    text_color=("#DCE4EE", "#DCE4EE") if i == 1 else ("gray14", "gray84"),
                    hover=False,
                    height=28,
                )
                btn.pack(fill="x", padx=4, pady=1)
            settle(standin, max(ctx.settle_ms, 500))
            return ShotResult(shot.id, "ok", "File menu stand-in", ctx.grab(standin, shot))

        _save_rgba(dest, image, ctx.app)
        return ShotResult(shot.id, "ok", "File menu tk_popup", dest)
    finally:
        with contextlib.suppress(Exception):
            file_menu.unpost()
        with contextlib.suppress(Exception):
            file_menu.grab_release()
        if standin is not None and standin.winfo_exists():
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


def shot_import_davidson_progress(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    """Import dialog mid-run (Cancel), then also capture Done from the same dialog."""
    from anonymizer.utils.translate import _ as tr

    # Stall long enough for screencapture + settle while Cancel is still showing.
    dlg, paths, anon, real, stalled = _open_davidson_import_dialog(ctx, stall_seconds=4.0)
    try:
        for _i in range(80):
            settle(ctx.app, 40)
            try:
                btn = str(dlg._cancel_button.cget("text"))
                subtitle = str(dlg._sub_title_label.cget("text"))
            except Exception:
                btn, subtitle = "", ""
            if btn == tr("Cancel") and "Importing" in subtitle:
                break

        progress_dest = ctx.grab(dlg, shot, settle_ms=150)

        # Same dialog → finished state for Done shot (avoids a second racey import).
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

        settle(dlg, 400)
        done_shot = next((s for s in ctx.manifest.all_shots() if s.id == "ImportDavidson_Done"), None)
        if done_shot is not None:
            ctx.grab(dlg, done_shot, settle_ms=400)
            ctx._davidson_done_captured = True  # type: ignore[attr-defined]

        ctx.imported_keys.add("davidson_cxr")
        return ShotResult(shot.id, "ok", f"progress {len(paths)} file(s)", progress_dest)
    finally:
        if stalled:
            anon.anonymize_file = real  # type: ignore[method-assign]
        if dlg.winfo_exists():
            close_toplevel(dlg)


def shot_import_davidson_done(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    """Import dialog finished: success PHI→ID line and Close."""
    from anonymizer.utils.translate import _ as tr

    dest = ctx.dest(shot)
    if getattr(ctx, "_davidson_done_captured", False) and dest.exists() and dest.stat().st_size > 1000:
        return ShotResult(shot.id, "ok", "captured with Progress", dest)

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


def shot_import_files(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    """Legacy multi-fixture import dialog (kept for optional --only ImportFilesDialog)."""
    from collections import defaultdict
    from pathlib import Path

    from anonymizer.view.project.import_files_dialog import ImportFilesDialog

    _ensure_project(ctx)
    fixture = _fixture_from_deps(shot.deps) or "test_dcm_files"
    paths = collect_import_paths(fixture)
    by_parent: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        by_parent[Path(path).parent.name].append(path)
    sample: list[str] = []
    for group in by_parent.values():
        sample.extend(group[:4])
        if len(sample) >= 28:
            break
    if len(sample) < 8:
        sample = paths[:28]
    dlg = ImportFilesDialog(ctx.app, ctx.app.controller.anonymizer, sample)
    try:
        settle(ctx.app, max(ctx.settle_ms, 800))
        dest = ctx.grab(dlg, shot, settle_ms=max(ctx.settle_ms, 700))
        for _ in range(400):
            if getattr(dlg, "_worker_done", False) or not dlg.winfo_exists():
                break
            settle(ctx.app, 50)
        ctx.imported_keys.add(fixture)
        for key in ("davidson_cxr", "Brain_Ax_EarlyArt", "chest", "head", "abdomen", "us"):
            ctx.imported_keys.add(key)
        return ShotResult(shot.id, "ok", f"{len(sample)} files from {fixture}", dest)
    finally:
        if dlg.winfo_exists():
            close_toplevel(dlg)


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


def shot_dataset(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    # Import several fixture studies so the Study/Series tree has a countable list.
    _import_fixtures(
        ctx,
        "davidson_cxr",
        "Brain_Ax_EarlyArt",
        "chest",
        "head",
        "abdomen",
        "us",
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
    dest = ctx.grab(view, shot, geometry="1280x800", settle_ms=max(ctx.settle_ms, 700))
    return ShotResult(shot.id, "ok", f"{study_count} studies / {series_count} series", dest)


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
    from anonymizer.controller.runner import OcrEditContext

    fixture = _fixture_from_deps(shot.deps) or "davidson_cxr"
    view, series = _series_view_for_fixture(ctx, fixture)
    try:
        # Default whitelist + Frame context
        try:
            view.edit_context = OcrEditContext.FRAME
            if hasattr(view, "_load_whitelist_match_settings"):
                view._load_whitelist_match_settings()
        except Exception as exc:
            logger.warning("Whitelist/frame setup: %s", exc)
        settle(view, ctx.settle_ms)

        actions = list((shot.recipe or {}).get("actions") or [])
        if "detect_text" in actions:
            view.detect_text_button_clicked()
            for _i in range(200):
                settle(ctx.app, 100)
                if not getattr(view, "_job_running", False):
                    break
            settle(view, max(ctx.settle_ms, 600))
        if "remove_text" in actions:
            try:
                if hasattr(view, "remove_text_button_clicked"):
                    view.remove_text_button_clicked()
                for _i in range(200):
                    settle(ctx.app, 100)
                    if not getattr(view, "_job_running", False):
                        break
                settle(view, max(ctx.settle_ms, 800))
            except Exception as exc:
                logger.warning("Remove Text: %s", exc)
        return ShotResult(shot.id, "ok", f"{fixture}:{actions}", ctx.grab(view, shot, settle_ms=max(ctx.settle_ms, 700)))
    finally:
        close_toplevel(view)


def shot_process_harmonize(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
    from anonymizer.view.ai.harmonize_results import show_harmonize_results_view
    from anonymizer.view.series.series import show_series_view
    from pydicom import dcmread

    fixture = _fixture_from_deps(shot.deps) or "Brain_Ax_EarlyArt"
    _import_fixtures(ctx, fixture)
    series = series_for_fixture(ctx.app.controller.model.images_dir(), fixture)
    if series is None:
        raise RuntimeError(f"No series for {fixture}")
    dcms = sorted(series.glob("*.dcm"))
    ds = dcmread(dcms[0], stop_before_pixels=True)
    include_brain = "segment_brain_features" in list((shot.recipe or {}).get("actions") or [])
    parent = ctx.app.dashboard or ctx.app
    series_view = show_series_view(parent, controller=ctx.app.controller, series_path=series, fonts=ctx.app.fonts)
    try:
        settle(series_view, max(ctx.settle_ms, 800))
        view = show_harmonize_results_view(
            parent,
            series_path=series,
            ds=ds,
            fonts=ctx.app.fonts,
            anon_model=ctx.app.controller.anonymizer.model,
            include_brain_structures=include_brain,
        )
        # Grab while results window is open — do not wait for full TS job.
        settle(view, max(ctx.settle_ms, 1200))
        dest = ctx.grab(view, shot)
        close_toplevel(view)
        return ShotResult(shot.id, "ok", f"brain={include_brain}", dest)
    finally:
        if series_view is not None:
            close_toplevel(series_view)


def shot_process_face_blur(ctx: CaptureContext, shot: ShotSpec) -> ShotResult:
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
        # Grab loading shell or review UI within a bounded wait (soft path).
        for _ in range(60):
            settle(ctx.app, 100)
            try:
                if dlg.winfo_viewable():
                    break
            except Exception:
                break
        settle(dlg, ctx.settle_ms)
        return ShotResult(shot.id, "ok", "gaussian", ctx.grab(dlg, shot))
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
    "ImportDavidson_Progress": shot_import_davidson_progress,
    "ImportDavidson_Done": shot_import_davidson_done,
    "ImportFilesDialog": shot_import_files,
    "OrthancCT_Query": shot_orthanc_ct_query,
    "OrthancCT_Importing": shot_orthanc_ct_importing,
    "OrthancCT_Imported": shot_orthanc_ct_imported,
    "QueryRetrieveImport": shot_query,
    "Dataset": shot_dataset,
    "SeriesView_Review": shot_series_review,
    "AiBatchOptions": shot_ai_batch_options,
    "SendView": shot_send_view,
    "Process_RemovePixel_Whitelist": shot_process_remove_pixel,
    "Process_RemovePixel_Detect": shot_process_remove_pixel,
    "Process_RemovePixel_Remove": shot_process_remove_pixel,
    "Process_Harmonize_Description": shot_process_harmonize,
    "Process_Harmonize_BrainFeatures": shot_process_harmonize,
    "Process_FaceBlur_Gaussian": shot_process_face_blur,
}


def _teardown_capture_app(app: object) -> None:
    import contextlib

    for attr in ("query_view", "export_view", "dataset_view"):
        view = getattr(app, attr, None)
        if view is not None:
            with contextlib.suppress(Exception):
                close_toplevel(view)
            with contextlib.suppress(Exception):
                setattr(app, attr, None)
    dashboard = getattr(app, "dashboard", None)
    if dashboard is not None:
        with contextlib.suppress(Exception):
            dashboard.destroy()
        with contextlib.suppress(Exception):
            app.dashboard = None
    ctrl = getattr(app, "controller", None)
    if ctrl is not None:
        with contextlib.suppress(Exception):
            ctrl.stop_scp()
        with contextlib.suppress(Exception):
            ctrl.anonymizer.stop()
        with contextlib.suppress(Exception):
            app.controller = None
    with contextlib.suppress(Exception):
        app.quit()
    with contextlib.suppress(Exception):
        app.destroy()


def _existing(path: Path) -> Path | None:
    if path.is_file() and path.stat().st_size > 0:
        return path
    return None


def run_language(
    language: str,
    *,
    only: set[str] | None,
    settle_ms: int,
    keep_work: bool,
    allow_placeholder: bool,
    skip_existing: bool,
    force_shots: set[str],
) -> list[ShotResult]:
    import customtkinter as ctk
    from anonymizer.anonymizer import Anonymizer
    from anonymizer.utils.translate import set_language_code
    from anonymizer.view.common.ctk_safe import install_safe_scaling_tracker

    manifest = load_manifest()
    if language not in manifest.languages:
        raise ValueError(f"Unsupported language {language!r}")

    shots = [s for s in manifest.all_shots() if only is None or s.id in only]
    results: list[ShotResult] = []

    def should_skip(shot: ShotSpec) -> Path | None:
        if not skip_existing or shot.id in force_shots:
            return None
        return _existing(manifest.output_path(language, shot))

    pending = [s for s in shots if should_skip(s) is None]
    for shot in shots:
        existing = should_skip(shot)
        if existing is not None:
            result = ShotResult(shot.id, "skipped", f"exists ({existing.stat().st_size} bytes)", existing)
            results.append(result)
            print(f"[SKIP] {result.shot_id}: {result.detail} → {result.path}")

    if not pending:
        print(f"Nothing to capture for {language}.")
        return results

    print(f"Will capture {len(pending)} shot(s): {', '.join(s.id for s in pending)}")

    work_dir = CAPTURE_WORK / language
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = _prepare_environment(work_dir)

    set_language_code(language)
    install_safe_scaling_tracker()

    # Dialog __init__ paths call wait_visibility(); that can hang forever on macOS.
    import tkinter as tk

    def _capture_safe_wait_visibility(self, window=None):  # type: ignore[no-untyped-def]
        wait_mapped(window or self)

    tk.Misc.wait_visibility = _capture_safe_wait_visibility  # type: ignore[method-assign]

    app = Anonymizer(logs_dir)
    set_language_code(language)
    ctk.set_appearance_mode("Light")
    settle(app, settle_ms)

    # Never block capture on Tk messageboxes.
    from tkinter import messagebox as tk_messagebox

    tk_messagebox.showerror = lambda *a, **k: "ok"  # type: ignore[assignment]
    tk_messagebox.showwarning = lambda *a, **k: "ok"  # type: ignore[assignment]
    tk_messagebox.showinfo = lambda *a, **k: "ok"  # type: ignore[assignment]
    tk_messagebox.askyesno = lambda *a, **k: True  # type: ignore[assignment]
    tk_messagebox.askokcancel = lambda *a, **k: True  # type: ignore[assignment]

    ctx = CaptureContext(
        app=app,
        manifest=manifest,
        language=language,
        settle_ms=settle_ms,
        allow_placeholder=allow_placeholder,
        work_dir=work_dir,
        results=results,
    )

    try:
        for shot in pending:
            handler = SHOT_HANDLERS.get(shot.id)
            if handler is None:
                _record(ctx, ShotResult(shot.id, "hard_fail", f"No handler for {shot.id}"))
                continue
            try:
                if shot.id == "Welcome" and ctx.project_open:
                    raise RuntimeError("Welcome must run before project open")
                result = handler(ctx, shot)
                _record(ctx, result)
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                logger.error("%s failed: %s\n%s", shot.id, detail, traceback.format_exc())
                status = "soft_fail" if shot.soft else "hard_fail"
                _record(ctx, ShotResult(shot.id, status, detail))
    finally:
        try:
            _teardown_capture_app(app)
        except Exception:
            logger.exception("teardown failed")
        if not keep_work and work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)

    return ctx.results


def main(argv: list[str] | None = None) -> int:
    manifest = load_manifest()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--language", choices=sorted(manifest.languages), default="en_US")
    parser.add_argument("--all-languages", action="store_true")
    parser.add_argument("--only", nargs="+", metavar="SHOT")
    parser.add_argument("--settle-ms", type=int, default=500)
    parser.add_argument("--keep-work", action="store_true")
    parser.add_argument("--allow-placeholder", action="store_true")
    parser.add_argument(
        "--skip-existing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip shots whose PNG already exists (default: true)",
    )
    parser.add_argument("--force", action="store_true", help="Same as --no-skip-existing")
    parser.add_argument("--force-shot", nargs="+", metavar="SHOT")
    parser.add_argument("--skip-capture-check", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    languages = list(manifest.languages) if args.all_languages else [args.language]
    only = set(args.only) if args.only else None
    force_shots = set(args.force_shot or ())
    skip_existing = False if args.force else bool(args.skip_existing)
    known = {s.id for s in manifest.all_shots()}
    if only:
        unknown = only - known
        if unknown:
            parser.error(f"Unknown shot id(s): {sorted(unknown)}")
    if force_shots - known:
        parser.error(f"Unknown --force-shot id(s): {sorted(force_shots - known)}")

    if sys.platform != "darwin" and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print("ERROR: No DISPLAY/WAYLAND_DISPLAY", file=sys.stderr)
        return 2

    needs_ui = False
    for language in languages:
        for shot in manifest.all_shots():
            if only and shot.id not in only:
                continue
            if not skip_existing or shot.id in force_shots or _existing(manifest.output_path(language, shot)) is None:
                needs_ui = True
                break
        if needs_ui:
            break

    if needs_ui and not args.skip_capture_check and not args.allow_placeholder and not screen_capture_available():
        print(
            "ERROR: Screen capture unavailable. Grant Screen Recording on macOS, or use --allow-placeholder.",
            file=sys.stderr,
        )
        return 2

    all_results: list[ShotResult] = []
    for language in languages:
        print(f"\n=== Capturing language={language} → {manifest.languages[language]}/ ===")
        all_results.extend(
            run_language(
                language,
                only=only,
                settle_ms=args.settle_ms,
                keep_work=args.keep_work,
                allow_placeholder=args.allow_placeholder,
                skip_existing=skip_existing,
                force_shots=force_shots,
            )
        )

    print()
    print(f"{'Shot':<32} {'Status':<10} Detail")
    print("-" * 80)
    for r in all_results:
        print(f"{r.shot_id:<32} {r.status:<10} {r.detail}")
    hard = [r for r in all_results if r.status == "hard_fail"]
    soft = [r for r in all_results if r.status == "soft_fail"]
    ok = [r for r in all_results if r.status == "ok"]
    skipped = [r for r in all_results if r.status == "skipped"]
    print(f"\nSummary: {len(ok)} ok, {len(skipped)} skipped, {len(soft)} soft-fail, {len(hard)} hard-fail")
    code = 1 if hard else 0
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


if __name__ == "__main__":
    raise SystemExit(main())
