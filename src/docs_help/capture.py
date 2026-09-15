"""Capture context, project helpers, and language runner for MkDocs help shots.

The shot sequence is OS-agnostic: languages, chapter order, handlers, Harmonize,
TSEG cache, and resume (``exists``) are identical on macOS and Windows. The host
OS only selects the grab backend and the dest folder ``shots/<macos|windows>/``.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import traceback
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docs_help.manifest import ShotSpec, load_manifest
from docs_help.platform import close_toplevel, grab_widget, settle, wait_mapped
from docs_help.project_setup import (
    capture_project_exists,
    collect_import_paths,
    create_capture_project,
    discover_imported_fixtures,
)

logger = logging.getLogger("docs_help")

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "src" / "anonymizer"
CAPTURE_WORK = REPO_ROOT / "docs" / ".capture_work"


_CAPTURE_OSES = ("macos", "windows")


@dataclass
class ShotResult:
    shot_id: str
    status: str
    detail: str = ""
    path: Path | None = None
    language: str = ""
    capture_os: str = ""


@dataclass
class CaptureContext:
    app: Any
    manifest: Any
    language: str
    settle_ms: int
    capture_os: str = "macos"
    allow_placeholder: bool = False
    reset_work: bool = False
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
    """Match ``anonymizer.main``: run from package dir and point TS at local weights."""
    os.chdir(PACKAGE_DIR)
    # Keep public/private/… ASCII even when UI language translates those labels
    # (German öffentlich breaks SimpleITK NIfTI writes on Windows).
    os.environ["ANONYMIZER_ASCII_STORAGE_DIRS"] = "1"
    tseg_home = (PACKAGE_DIR / "assets" / "ai" / "tseg").resolve()
    tseg_weights = tseg_home / "nnunet" / "results"
    tseg_home.mkdir(parents=True, exist_ok=True)
    tseg_weights.mkdir(parents=True, exist_ok=True)
    os.environ["TOTALSEG_HOME_DIR"] = str(tseg_home)
    os.environ["TOTALSEG_WEIGHTS_PATH"] = str(tseg_weights)
    logger.info("TOTALSEG_HOME_DIR=%s", tseg_home)
    logs_dir = work_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def _announce(message: str) -> None:
    """Always-visible stepwise progress for terminal monitoring."""
    print(message, flush=True)
    logger.info("%s", message)


def _record(ctx: CaptureContext, result: ShotResult) -> None:
    if not result.language:
        result.language = ctx.language
    if not result.capture_os:
        result.capture_os = ctx.capture_os
    ctx.results.append(result)
    mark = {"ok": "OK", "exists": "EXISTS", "skipped": "EXISTS", "soft_fail": "SOFT", "hard_fail": "FAIL"}.get(
        result.status, result.status
    )
    where = f" → {result.path}" if result.path else ""
    _announce(f"[{mark}] {ctx.language} {result.shot_id}: {result.detail}{where}")


def _shots_in_results(results: list[ShotResult], shot_order: Sequence[str] | None) -> list[str]:
    seen = {result.shot_id for result in results}
    if shot_order:
        ordered = [shot_id for shot_id in shot_order if shot_id in seen]
        ordered.extend(shot_id for shot_id in seen if shot_id not in shot_order)
        return ordered
    ordered: list[str] = []
    for result in results:
        if result.shot_id not in ordered:
            ordered.append(result.shot_id)
    return ordered


def _png_on_disk(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _shot_languages_by_os(
    shot: ShotSpec,
    *,
    languages: Sequence[str],
    manifest: Any,
    capture_oses: Sequence[str] = _CAPTURE_OSES,
) -> dict[str, list[str]]:
    """Languages with a PNG for ``shot``, keyed by OS (empty list if none)."""
    return {
        os_name: [
            lang
            for lang in languages
            if _png_on_disk(manifest.output_path(lang, shot, capture_os=os_name))
        ]
        for os_name in capture_oses
    }


def format_capture_report(
    results: list[ShotResult],
    *,
    shot_order: Sequence[str] | None = None,
    languages: Sequence[str] | None = None,
    capture_os: str | None = None,
) -> str:
    """One row per shot: a language list per OS column."""
    del capture_os
    manifest = load_manifest()
    expected = [str(code) for code in languages] if languages else list(manifest.language_codes())
    expected_set = set(expected)
    os_names = list(_CAPTURE_OSES)
    lang_width = max(len(" ".join(expected)), 18)
    if shot_order:
        shot_ids = list(shot_order)
    else:
        shot_ids = _shots_in_results(results, None)

    incomplete = 0
    rows: list[str] = []
    for shot_id in shot_ids:
        shot = manifest.shot_by_id(shot_id)
        if shot is None:
            continue
        by_os = _shot_languages_by_os(
            shot, languages=expected, manifest=manifest, capture_oses=os_names
        )
        cells: list[str] = []
        row_incomplete = False
        for os_name in os_names:
            langs = by_os.get(os_name) or []
            if set(langs) != expected_set:
                row_incomplete = True
            cells.append(" ".join(langs) if langs else "-")
        if row_incomplete:
            incomplete += 1
            mark = "* "
        else:
            mark = "  "
        os_cols = "".join(f"{cell:<{lang_width}} " for cell in cells).rstrip()
        rows.append(f"{mark}{shot_id:<32} {os_cols}")

    header_os = "".join(f"{name:<{lang_width}} " for name in os_names).rstrip()
    lines = [
        f"{'Shot':<34} {header_os}",
        "-" * (36 + lang_width * len(os_names)),
        *rows,
        "",
        f"Summary: {len(rows)} shot(s), {len(rows) - incomplete} complete, {incomplete} incomplete",
    ]
    return "\n".join(lines)


def _ensure_project(ctx: CaptureContext) -> None:
    if ctx.project_open:
        return
    project_dir = ctx.work_dir / "project"
    if capture_project_exists(project_dir) and not ctx.reset_work:
        _announce(f"STEP resume capture project {project_dir}")
    else:
        if project_dir.exists() and ctx.reset_work:
            shutil.rmtree(project_dir)
        create_capture_project(project_dir)
        _announce(f"STEP create capture project {project_dir}")
    ctx.app.open_project(project_dir)
    settle(ctx.app, ctx.settle_ms)
    if not ctx.app.controller:
        raise RuntimeError("ProjectController not created after open_project")
    ctx.project_open = True
    images = ctx.app.controller.model.images_dir()
    found = discover_imported_fixtures(Path(images))
    if found:
        ctx.imported_keys.update(found)
        _announce(f"STEP already imported fixtures: {', '.join(sorted(found))}")


def _ensure_modalities_for_fixtures(ctx: CaptureContext, keys: list[str]) -> None:
    """Enable storage classes needed by fixtures (e.g. US for ultrasound demos)."""
    need_us = any(
        k in {"us", "us_rgb_single_frame", "us_mf", "us_multi_frame_grayscale"}
        or "us_rgb" in k.lower()
        or "us_multi" in k.lower()
        for k in keys
    )
    if not need_us:
        return
    model = ctx.app.controller.model
    if "US" in model.modalities:
        return
    model.modalities = list(model.modalities) + ["US"]
    model.set_storage_classes_from_modalities()
    ctx.app.controller.save_model()
    logger.info("Enabled US modality for capture project (%d storage classes)", len(model.storage_classes))


def _seed_imported_fixture_caches(ctx: CaptureContext, keys: list[str]) -> None:
    """Copy saved ``0_TS_SEG`` onto imported series so Harmonize skips TotalSegmentator."""
    from docs_help.fixture_cache import seed_tseg_cache
    from docs_help.project_setup import series_for_fixture

    images = ctx.app.controller.model.images_dir()
    for key in keys:
        series = series_for_fixture(images, key)
        if series is None:
            continue
        if seed_tseg_cache(series, key):
            logger.info("TS cache ready for fixture %s at %s", key, series)


def _import_fixtures(ctx: CaptureContext, *keys: str) -> None:
    _ensure_project(ctx)
    needed = [k for k in keys if k not in ctx.imported_keys]
    if not needed:
        return
    _ensure_modalities_for_fixtures(ctx, needed)
    paths = collect_import_paths(*needed)
    _announce(f"STEP import fixtures {needed} ({len(paths)} file(s))")
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
    _seed_imported_fixture_caches(ctx, needed)


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



def _teardown_capture_app(app: object, *, timeout_s: float = 2.0) -> None:
    import contextlib
    import threading

    from docs_help.interrupt import hard_exit

    try:
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
            # pynetdicom socketserver.shutdown() can wait forever; don't block Ctrl+C.
            def _stop_network() -> None:
                with contextlib.suppress(Exception):
                    ctrl.stop_scp()
                with contextlib.suppress(Exception):
                    ctrl.anonymizer.stop()

            stopper = threading.Thread(target=_stop_network, daemon=True, name="docs_help-teardown")
            stopper.start()
            stopper.join(timeout_s)
            with contextlib.suppress(Exception):
                app.controller = None
        with contextlib.suppress(Exception):
            app.quit()
        with contextlib.suppress(Exception):
            app.destroy()
    except KeyboardInterrupt:
        hard_exit()


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
    capture_os: str | None = None,
    reset_work: bool = False,
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
    total = len(shots)

    _announce(f"=== language={language} platform={capture_os} ===")
    _announce(f"    chapters: {manifest.chapter_sequence_label()}")

    def should_skip(shot: ShotSpec) -> Path | None:
        if not skip_existing or shot.id in force_shots:
            return None
        return _existing(manifest.output_path(language, shot, capture_os=capture_os))

    pending = [s for s in shots if should_skip(s) is None]
    for catalog_i, shot in enumerate(shots, start=1):
        existing = should_skip(shot)
        if existing is not None:
            result = ShotResult(
                shot.id,
                "exists",
                f"already captured ({existing.stat().st_size} bytes)",
                existing,
                language,
                capture_os or "",
            )
            results.append(result)
            _announce(
                f"[EXISTS] [{catalog_i}/{total}] {language}  {shot.chapter_label}  {result.shot_id}: "
                f"{result.detail} → {result.path}"
            )

    work_dir = CAPTURE_WORK / language
    from docs_help.fixture_cache import TSEG_CACHE_ROOT, harvest_tseg_cache_from_tree

    if work_dir.exists():
        harvest_tseg_cache_from_tree(work_dir)
    if reset_work and work_dir.exists():
        _announce(f"STEP reset-work: wiping {work_dir} (fixture_cache kept at {TSEG_CACHE_ROOT})")
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    if not pending:
        _announce(f"Nothing to capture for {language} (all {total} shot(s) already on disk).")
        return results

    _announce(f"    pending={len(pending)}/{total}: {', '.join(s.id for s in pending)}")
    _announce(f"    work={work_dir}")
    _announce(f"    fixture_cache={TSEG_CACHE_ROOT}")
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
        reset_work=reset_work,
        work_dir=work_dir,
        results=results,
    )

    try:
        from docs_help.handlers import SHOT_HANDLERS

        for catalog_i, shot in enumerate(shots, start=1):
            existing = should_skip(shot)
            if existing is not None:
                continue
            handler = SHOT_HANDLERS.get(shot.id)
            _announce(
                f"--- [{catalog_i}/{total}] {language}  "
                f"{shot.chapter_label}  {shot.id} ---"
            )
            if shot.caption:
                _announce(f"    {shot.caption}")
            if handler is None:
                _record(ctx, ShotResult(shot.id, "hard_fail", f"No handler for {shot.id}"))
                continue
            try:
                if shot.id == "Welcome" and ctx.project_open:
                    raise RuntimeError("Welcome must run before project open")
                result = handler(ctx, shot)
                _record(ctx, result)
            except KeyboardInterrupt:
                from docs_help.interrupt import hard_exit

                hard_exit()
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                logger.error("%s failed: %s\n%s", shot.id, detail, traceback.format_exc())
                status = "soft_fail" if shot.soft else "hard_fail"
                _record(ctx, ShotResult(shot.id, status, detail))
                _announce(
                    f"STEP continue after {status} on {shot.id} "
                    "(re-run the same command to resume remaining shots)"
                )
    except KeyboardInterrupt:
        from docs_help.interrupt import hard_exit

        hard_exit()
    finally:
        try:
            _teardown_capture_app(app)
        except KeyboardInterrupt:
            from docs_help.interrupt import hard_exit

            hard_exit()
        except Exception:
            logger.exception("teardown failed")
        if not keep_work and work_dir.exists():
            _announce(f"STEP remove work dir {work_dir} (--no-keep-work)")
            shutil.rmtree(work_dir, ignore_errors=True)
        else:
            _announce(f"STEP keep work dir {work_dir} for resume")

    return ctx.results

