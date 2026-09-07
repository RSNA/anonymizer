"""Capture context, project helpers, and language runner for MkDocs help shots."""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docs_help.manifest import ShotSpec, load_manifest
from docs_help.platform import close_toplevel, grab_widget, settle, wait_mapped
from docs_help.project_setup import collect_import_paths, create_capture_project

logger = logging.getLogger("docs_help")

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "anonymizer"
CAPTURE_WORK = REPO_ROOT / "docs" / ".capture_work"


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
    capture_os: str = "macos"
    allow_placeholder: bool = False
    work_dir: Path = field(default_factory=Path)
    imported_keys: set[str] = field(default_factory=set)
    project_open: bool = False
    results: list[ShotResult] = field(default_factory=list)

    def dest(self, shot: ShotSpec) -> Path:
        return self.manifest.output_path(self.language, shot, capture_os=self.capture_os)

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


def _ensure_modalities_for_fixtures(ctx: CaptureContext, keys: list[str]) -> None:
    """Enable storage classes needed by fixtures (e.g. US for ultrasound demos)."""
    need_us = any(k in {"us", "us_rgb_single_frame", "us_mf"} or "us_rgb" in k.lower() for k in keys)
    if not need_us:
        return
    model = ctx.app.controller.model
    if "US" in model.modalities:
        return
    model.modalities = list(model.modalities) + ["US"]
    model.set_storage_classes_from_modalities()
    ctx.app.controller.save_model()
    logger.info("Enabled US modality for capture project (%d storage classes)", len(model.storage_classes))


def _import_fixtures(ctx: CaptureContext, *keys: str) -> None:
    _ensure_project(ctx)
    needed = [k for k in keys if k not in ctx.imported_keys]
    if not needed:
        return
    _ensure_modalities_for_fixtures(ctx, needed)
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
    capture_os: str = "macos",
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
        return _existing(manifest.output_path(language, shot, capture_os=capture_os))

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
        capture_os=capture_os,
        allow_placeholder=allow_placeholder,
        work_dir=work_dir,
        results=results,
    )

    try:
        for shot in pending:
            from docs_help.handlers import SHOT_HANDLERS
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

