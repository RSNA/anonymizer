"""Reusable Series View → Harmonize capture workflow for help screenshots.

Keeps the clinician-manual sequence stable across languages and re-runs:

1. Open ``Brain_Ax_EarlyArt`` in **Series View** (never jump from Dashboard alone).
2. Start **Harmonize Description** from that Series View.
3. Control the brain-structures Yes/No prompt (auto answer, or show a
   captureable stand-in dialog for the prompt shot).
4. Wait until the Playbook results table is fully populated.
5. Optionally Accept, then latch all segmentation overlays on the middle slice.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterator

import customtkinter as ctk

from docs_help.platform import (
    close_toplevel,
    grab_stacked_windows,
    grab_widget,
    grab_widgets_union,
    settle,
    wait_mapped,
)
from docs_help.project_setup import series_for_fixture

logger = logging.getLogger(__name__)

# Head CT Harmonize (with TotalSegmentator) can take several minutes on first run.
DEFAULT_HARMONIZE_TIMEOUT_S = 900.0
BRAIN_PROMPT_TITLE_MARKERS = ("brain structures", "brain structure")


class BrainPromptPolicy(str, Enum):
    """How capture handles the CT-head brain-structures confirmation."""

    AUTO_NO = "auto_no"
    AUTO_YES = "auto_yes"
    CAPTURE = "capture"  # show a Tk stand-in, allow grab, then answer


@dataclass
class HarmonizeCaptureSession:
    """Open Series View + Harmonize dialog for one fixture."""

    series_view: Any
    series_path: Path
    harmonize_view: Any | None = None
    brain_prompt: Any | None = None


def _is_brain_structures_prompt(title: object, message: object) -> bool:
    blob = f"{title}\n{message}".casefold()
    return any(marker in blob for marker in BRAIN_PROMPT_TITLE_MARKERS)


def brain_structures_prompt_copy() -> tuple[str, str]:
    """Title + message used by the real Harmonize brain-structures askyesno."""
    from anonymizer.utils.translate import _
    from anonymizer.view.ai.features.catalog import AiFeatureId, feature_description

    title = _("Brain structures")
    message = (
        _("This appears to be a CT head study. Run detailed brain structure segmentation?")
        + "\n\n"
        + feature_description(AiFeatureId.BRAIN_STRUCTURES.value)
    )
    return title, message


def show_brain_prompt_standin(
    parent: Any,
    *,
    title: str,
    message: str,
    on_yes: Callable[[], None] | None = None,
    on_no: Callable[[], None] | None = None,
) -> Any:
    """Captureable Yes/No dialog matching the Harmonize brain-structures prompt.

    Native ``messagebox.askyesno`` cannot be composited into docs screenshots from
    the same Tk thread; this stand-in uses the same copy and button labels.
    """
    dlg = ctk.CTkToplevel(master=parent)
    dlg.title(title)
    dlg.resizable(False, False)
    if parent is not None:
        try:
            dlg.transient(parent)
        except Exception:
            pass
    frame = ctk.CTkFrame(dlg)
    frame.pack(fill="both", expand=True, padx=16, pady=16)
    ctk.CTkLabel(frame, text=message, wraplength=420, justify="left", anchor="w").pack(fill="x", pady=(0, 16))
    buttons = ctk.CTkFrame(frame, fg_color="transparent")
    buttons.pack(fill="x")

    def _yes() -> None:
        if on_yes is not None:
            on_yes()
        close_toplevel(dlg)

    def _no() -> None:
        if on_no is not None:
            on_no()
        close_toplevel(dlg)

    ctk.CTkButton(buttons, text="No", width=90, command=_no).pack(side="right", padx=(8, 0))
    ctk.CTkButton(buttons, text="Yes", width=90, command=_yes).pack(side="right")
    dlg.update_idletasks()
    try:
        if parent is not None:
            px = int(parent.winfo_rootx()) + 80
            py = int(parent.winfo_rooty()) + 120
            dlg.geometry(f"+{px}+{py}")
        dlg.lift()
        dlg.attributes("-topmost", True)
    except Exception:
        pass
    return dlg


@contextmanager
def brain_prompt_policy(
    policy: BrainPromptPolicy,
    *,
    answer_after_capture: bool = True,
    on_prompt_ready: Callable[[Any], None] | None = None,
) -> Iterator[dict[str, Any]]:
    """Temporarily replace ``messagebox.askyesno`` for Harmonize capture runs."""
    from tkinter import messagebox as tk_messagebox

    state: dict[str, Any] = {"dialog": None, "answered": None}
    previous = tk_messagebox.askyesno

    def _auto(answer: bool):
        def _ask(title=None, message=None, **kwargs):  # type: ignore[no-untyped-def]
            if _is_brain_structures_prompt(title, message):
                state["answered"] = answer
                logger.info("Brain prompt auto-%s", "yes" if answer else "no")
                return answer
            return previous(title, message, **kwargs)

        return _ask

    def _capture_ask(title=None, message=None, **kwargs):  # type: ignore[no-untyped-def]
        if not _is_brain_structures_prompt(title, message):
            return previous(title, message, **kwargs)

        def _set(answer: bool) -> None:
            state["answered"] = answer

        dlg = show_brain_prompt_standin(
            kwargs.get("parent"),
            title=str(title or "Brain structures"),
            message=str(message or ""),
            on_yes=lambda: _set(True),
            on_no=lambda: _set(False),
        )
        state["dialog"] = dlg
        if on_prompt_ready is not None:
            on_prompt_ready(dlg)
        dlg.wait_window()
        if state["answered"] is None:
            state["answered"] = answer_after_capture
        return bool(state["answered"])

    if policy is BrainPromptPolicy.AUTO_NO:
        tk_messagebox.askyesno = _auto(False)  # type: ignore[assignment]
    elif policy is BrainPromptPolicy.AUTO_YES:
        tk_messagebox.askyesno = _auto(True)  # type: ignore[assignment]
    else:
        tk_messagebox.askyesno = _capture_ask  # type: ignore[assignment]

    try:
        yield state
    finally:
        tk_messagebox.askyesno = previous  # type: ignore[assignment]
        dlg = state.get("dialog")
        if dlg is not None:
            try:
                if dlg.winfo_exists():
                    close_toplevel(dlg)
            except Exception:
                pass


def open_series_view(ctx: Any, series_path: Path) -> Any:
    """Open an already-imported series in Series View."""
    from anonymizer.view.series.series import show_series_view

    parent = ctx.app.dashboard or ctx.app
    view = show_series_view(
        parent,
        controller=ctx.app.controller,
        series_path=series_path,
        fonts=ctx.app.fonts,
    )
    if view is None:
        raise RuntimeError(f"SeriesView failed for {series_path}")
    settle(view, max(getattr(ctx, "settle_ms", 400), 1200))
    wait_mapped(view, timeout_ms=2000)
    return view


def clear_series_analysis_cache(series_view: Any) -> None:
    """Clear TS/Harmonize cache so Harmonize can re-run without UI confirmations."""
    controller = getattr(series_view, "_controller", None)
    series_path = getattr(series_view, "_series_path", None)
    if controller is None or series_path is None:
        return
    try:
        from anonymizer.controller.ai.tseg.cache import resolve_series_cache_dir

        cache_dir = resolve_series_cache_dir(series_path)
    except Exception:
        cache_dir = None
    has_seg = False
    likely = getattr(series_view, "_seg_dir_likely_has_structures", None)
    if callable(likely):
        has_seg = bool(likely())
    if not has_seg and (cache_dir is None or not Path(cache_dir).is_dir()):
        return

    anon_uid = None
    anon_fn = getattr(series_view, "_anon_series_uid", None)
    if callable(anon_fn):
        anon_uid = anon_fn()
    logger.info("Clearing analysis cache for capture: %s", series_path)
    controller.clear_series_tseg_cache(series_path, anon_series_uid=anon_uid)
    finish = getattr(series_view, "_finish_clear_ts_cache", None)
    if callable(finish):
        finish()
    else:
        invalidate = getattr(series_view, "_invalidate_structure_overlays", None)
        if callable(invalidate):
            invalidate()
        refresh = getattr(series_view, "_refresh_analysis_cache_ui", None)
        if callable(refresh):
            refresh()
    settle(series_view, 400)


def start_harmonize_from_series_view(series_view: Any) -> Any:
    """Click Harmonize Description and return the HarmonizeResultsView."""
    from anonymizer.view.ai.harmonize_results import (
        HarmonizeResultsView,
        get_any_open_harmonize_view,
    )

    existing = get_any_open_harmonize_view()
    if existing is not None:
        try:
            existing.destroy()
        except Exception:
            pass
        try:
            series_view._harmonize_view = None
        except Exception:
            pass

    try:
        if hasattr(series_view, "harmonize_button"):
            series_view.harmonize_button.grid()
        series_view._set_series_interaction_enabled(True)
    except Exception as exc:
        logger.warning("Series View Harmonize chrome refresh: %s", exc)

    series_view.harmonize_description_button_clicked()
    settle(series_view, 300)
    view = getattr(series_view, "_harmonize_view", None) or get_any_open_harmonize_view()
    if view is None:
        for _ in range(50):
            settle(series_view, 50)
            view = getattr(series_view, "_harmonize_view", None) or get_any_open_harmonize_view()
            if view is not None:
                break
    if view is None or not isinstance(view, HarmonizeResultsView):
        raise RuntimeError("HarmonizeResultsView did not open from Series View")
    try:
        wait_mapped(view, timeout_ms=2000)
    except Exception:
        pass
    return view


def wait_harmonize_results_ready(harmonize_view: Any, *, timeout_s: float = DEFAULT_HARMONIZE_TIMEOUT_S) -> None:
    """Block until playbook results are shown (or error), pumping Tk."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        settle(harmonize_view, 200)
        if getattr(harmonize_view, "cancelled", False):
            raise RuntimeError("Harmonize was cancelled before results were ready")
        if getattr(harmonize_view, "error", None):
            raise RuntimeError(f"Harmonize failed: {harmonize_view.error}")
        if not getattr(harmonize_view, "_running", True) and getattr(harmonize_view, "result", None) is not None:
            tree = getattr(harmonize_view, "_playbook_tree", None)
            if tree is None or tree.get_children():
                return
    raise TimeoutError(f"Harmonize did not finish within {timeout_s:.0f}s")


def fit_harmonize_results_for_capture(harmonize_view: Any) -> None:
    """Expand the dialog so DICOM + Playbook tables are fully visible."""
    try:
        playbook = getattr(harmonize_view, "_playbook_tree", None)
        dicom = getattr(harmonize_view, "_dicom_tree", None)
        if playbook is not None:
            rows = max(len(playbook.get_children()), getattr(harmonize_view, "_PLAYBOOK_TREE_VISIBLE_ROWS", 8))
            playbook.configure(height=rows)
        if dicom is not None:
            rows = max(len(dicom.get_children()), getattr(harmonize_view, "_DICOM_TREE_VISIBLE_ROWS", 10))
            dicom.configure(height=rows)
        proposal = getattr(harmonize_view, "_proposal_frame", None)
        if proposal is not None:
            proposal.grid()
        harmonize_view.update_idletasks()
        width = max(int(getattr(harmonize_view, "MIN_WIDTH", 1200)), int(harmonize_view.winfo_reqwidth()))
        height = max(int(getattr(harmonize_view, "_min_height", 720)), int(harmonize_view.winfo_reqheight()) + 16)
        height = min(height, 920)
        harmonize_view.geometry(f"{width}x{height}")
        harmonize_view.update_idletasks()
    except Exception as exc:
        logger.warning("fit_harmonize_results_for_capture: %s", exc)


def layout_series_above_harmonize(series_view: Any, harmonize_view: Any, *, peek_px: int = 220) -> None:
    """Place Series View large on top and Harmonize lower so the series shows above it."""
    try:
        screen_w = int(series_view.winfo_screenwidth())
        screen_h = int(series_view.winfo_screenheight())
    except Exception:
        screen_w, screen_h = 1440, 900

    sv_w = min(1280, max(980, screen_w - 40))
    sv_h = min(900, max(700, screen_h - 50))
    series_view.geometry(f"{sv_w}x{sv_h}+16+28")
    try:
        series_view.deiconify()
        series_view.lift()
    except Exception:
        pass
    settle(series_view, 350)

    fit_harmonize_results_for_capture(harmonize_view)
    settle(harmonize_view, 250)
    try:
        hv_w = max(int(harmonize_view.winfo_width()), int(getattr(harmonize_view, "MIN_WIDTH", 1100)))
        hv_h = int(harmonize_view.winfo_height())
    except Exception:
        hv_w, hv_h = 1100, 720

    # Cap dialog height so Series View title bar + image strip remain visible above.
    max_hv_h = max(520, sv_h - peek_px - 40)
    if hv_h > max_hv_h:
        harmonize_view.geometry(f"{hv_w}x{max_hv_h}")
        settle(harmonize_view, 200)
        try:
            hv_h = int(harmonize_view.winfo_height())
        except Exception:
            hv_h = max_hv_h

    try:
        sx = int(series_view.winfo_rootx())
        sy = int(series_view.winfo_rooty())
        sv_w_now = int(series_view.winfo_width())
    except Exception:
        sx, sy, sv_w_now = 16, 28, sv_w

    dialog_x = sx + max(24, (sv_w_now - hv_w) // 2)
    dialog_y = sy + peek_px
    dialog_y = min(dialog_y, max(40, screen_h - hv_h - 24))
    harmonize_view.geometry(f"+{dialog_x}+{dialog_y}")
    try:
        series_view.lift()
        harmonize_view.lift()
        harmonize_view.focus_force()
    except Exception:
        pass
    settle(series_view, 300)
    settle(harmonize_view, 300)


def ensure_brain_structures_models() -> None:
    """Download Dataset409 brain_structures weights when missing (required for shot 3)."""
    from anonymizer.controller.ai.tseg.readiness import (
        TsWeightKind,
        brain_structures_ready,
        download_segmentation_model,
    )

    if brain_structures_ready():
        logger.info("Brain structures models already installed")
        return
    logger.info("Downloading brain structures models for Harmonize help screenshots…")
    ok = download_segmentation_model(TsWeightKind.BRAIN_STRUCTURES)
    if not ok or not brain_structures_ready():
        raise RuntimeError(
            "Brain structures models are not installed. Download them in AI Features "
            "(Brain structures) before capturing Process_Harmonize_SegmentedSeries."
        )


def precompute_brain_harmonize_cache(series_path: Path, anon_model=None) -> None:
    """Run Harmonize+brain structures without Tk (avoids TS/Tk segfaults during capture)."""
    from anonymizer.controller.ai.harmonize.pipeline import harmonize_series
    from anonymizer.controller.ai.tseg.config import BRAIN_STRUCTURE_FILES
    from anonymizer.controller.ai.tseg.segment import run_brain_structures_segmentation

    ensure_brain_structures_models()
    logger.info("Precomputing Harmonize+brain cache for %s", series_path)
    results = harmonize_series(
        [series_path],
        include_brain_structures=True,
        anon_model=anon_model,
    )
    if not results:
        raise RuntimeError("harmonize_series returned no results")
    err = getattr(results[0], "error", None)
    if err:
        raise RuntimeError(f"harmonize_series failed: {err}")

    seg_dir = series_path / "0_TS_SEG" / "seg"
    nifti = series_path / "0_TS_SEG" / "volume.nii.gz"
    present = [n for n in BRAIN_STRUCTURE_FILES if (seg_dir / f"{n}.nii.gz").is_file()]
    if len(present) < 8:
        if not nifti.is_file():
            raise RuntimeError(
                f"Harmonize finished without brain structures ({len(present)} masks) "
                f"and volume.nii.gz is missing under {series_path / '0_TS_SEG'}"
            )
        logger.warning(
            "Harmonize left only %d brain-structure masks; forcing brain_structures task",
            len(present),
        )
        run_brain_structures_segmentation(nifti, seg_dir)
        present = [n for n in BRAIN_STRUCTURE_FILES if (seg_dir / f"{n}.nii.gz").is_file()]
    if len(present) < 8:
        raise RuntimeError(
            f"Expected ≥8 brain-structure masks after precompute; got {len(present)}: {present}"
        )
    logger.info("Precompute complete for %s (%d brain-structure masks)", series_path, len(present))


def series_has_brain_structure_cache(series_path: Path) -> bool:
    """True when Harmonize already wrote detailed brain-structure masks for this series."""
    from anonymizer.controller.ai.tseg.config import BRAIN_STRUCTURE_FILES

    seg_dir = series_path / "0_TS_SEG" / "seg"
    if not seg_dir.is_dir():
        return False
    present = sum(1 for name in BRAIN_STRUCTURE_FILES if (seg_dir / f"{name}.nii.gz").is_file())
    return present >= 8


def brain_structure_latches_present(series_view: Any) -> list[str]:
    """Return latch names that belong to the licensed brain_structures task."""
    from anonymizer.controller.ai.tseg.config import BRAIN_STRUCTURE_FILES

    viewer = getattr(series_view, "image_viewer", None)
    if viewer is None:
        return []
    present = set(getattr(viewer, "_segmentation_button_meta", {}) or {})
    return [name for name in BRAIN_STRUCTURE_FILES if name in present]


def require_brain_structure_latches(series_view: Any, *, min_count: int = 8) -> list[str]:
    """Fail loudly when Harmonize did not produce detailed brain structure masks."""
    refresh = getattr(series_view, "_refresh_segmentation_controls", None)
    if callable(refresh):
        refresh()
    settle(series_view, 600)
    detail = brain_structure_latches_present(series_view)
    if len(detail) < min_count:
        viewer = series_view.image_viewer
        all_names = list(getattr(viewer, "_segmentation_button_meta", {}) or {})
        raise RuntimeError(
            "Expected detailed brain structure latches after Harmonize with brain Yes; "
            f"got {len(detail)} of {min_count}+ ({detail}). All latches: {all_names}. "
            "Ensure brain structures models are installed and the CT-head prompt answered Yes."
        )
    return detail


def cancel_harmonize_quietly(harmonize_view: Any, *, wait_s: float = 8.0) -> None:
    """Request cancel and wait briefly so teardown does not race TotalSegmentator."""
    if harmonize_view is None:
        return
    try:
        if not harmonize_view.winfo_exists():
            return
    except Exception:
        return
    try:
        if getattr(harmonize_view, "_running", False) or getattr(harmonize_view, "_saving", False):
            harmonize_view._on_cancel()
    except Exception as exc:
        logger.warning("cancel_harmonize_quietly: %s", exc)
        return
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        try:
            if not harmonize_view.winfo_exists():
                return
            if not getattr(harmonize_view, "_running", False):
                return
        except Exception:
            return
        settle(harmonize_view, 100)


def accept_harmonize_description(harmonize_view: Any, *, timeout_s: float = 180.0) -> None:
    """Press Yes / OK to save the proposed series description, then close."""
    if getattr(harmonize_view, "result", None) is None:
        raise RuntimeError("No Harmonize result to accept")
    yes = getattr(harmonize_view, "_yes_button", None)
    ok = getattr(harmonize_view, "_ok_button", None)
    try:
        yes_mapped = yes is not None and yes.winfo_ismapped() and str(yes.cget("state")) == "normal"
    except Exception:
        yes_mapped = False
    try:
        ok_mapped = ok is not None and ok.winfo_ismapped() and str(ok.cget("state")) == "normal"
    except Exception:
        ok_mapped = False

    if yes_mapped:
        harmonize_view._on_yes()
    elif ok_mapped:
        harmonize_view._on_ok()
    else:
        harmonize_view._on_yes()

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            exists = bool(harmonize_view.winfo_exists())
        except Exception:
            return
        if not exists:
            return
        settle(harmonize_view, 150)
        if not getattr(harmonize_view, "_running", False) and not getattr(harmonize_view, "_saving", False):
            if getattr(harmonize_view, "accepted", None) is True or not exists:
                close_toplevel(harmonize_view)
                return
    close_toplevel(harmonize_view)


def goto_middle_slice(series_view: Any) -> int:
    """Navigate ImageViewer to the middle frame; return the index."""
    viewer = getattr(series_view, "image_viewer", None)
    if viewer is None:
        raise RuntimeError("Series View has no image_viewer")
    n = int(getattr(viewer, "num_images", 0) or 0)
    if n <= 0:
        raise RuntimeError("Series View has no images loaded")
    mid = n // 2
    viewer.load_and_display_image(mid)
    settle(series_view, 400)
    return mid


def latch_all_segmentation_overlays(series_view: Any, *, settle_ms: int = 800) -> list[str]:
    """Activate every available segmentation latch button (brain + peers)."""
    refresh = getattr(series_view, "_refresh_segmentation_controls", None)
    if callable(refresh):
        refresh()
    settle(series_view, settle_ms)
    viewer = series_view.image_viewer
    names = list(getattr(viewer, "_segmentation_button_meta", {}) or {})
    if not names:
        raise RuntimeError("No segmentation latch buttons after Harmonize/brain run")
    for name in names:
        if name in viewer.get_active_segmentation_names():
            continue
        viewer._toggle_segmentation_structure(name)
        settle(series_view, 120)
    settle(series_view, max(settle_ms, 1000))
    ensure = getattr(series_view, "_ensure_segmentation_overlays_for_frame", None)
    if callable(ensure):
        ensure(viewer.current_image_index)
    settle(series_view, 400)
    return names


def latch_brain_and_detail_overlays(series_view: Any, *, settle_ms: int = 800) -> list[str]:
    """Latch detailed brain-structure buttons only (not whole-brain or skull).

    Cancels background full-volume contour threads after each latch: those workers
    touch Tk fonts and segfault under load when many structures are enabled for a
    help screenshot (current-slice overlay is already painted before the worker starts).
    """
    import gc

    from anonymizer.controller.ai.tseg.config import BRAIN_STRUCTURE_FILES

    refresh = getattr(series_view, "_refresh_segmentation_controls", None)
    if callable(refresh):
        refresh()
    settle(series_view, settle_ms)
    viewer = series_view.image_viewer
    available = set(getattr(viewer, "_segmentation_button_meta", {}) or {})
    names = [name for name in BRAIN_STRUCTURE_FILES if name in available]
    if not names:
        raise RuntimeError("No brain-structure latch buttons after Harmonize")

    # Docs shot: never leave whole-brain / skull latched — unlatch if already on.
    cancel_job = getattr(series_view, "_cancel_structure_contour_job", None)
    for exclude in ("brain", "skull"):
        if exclude in viewer.get_active_segmentation_names():
            viewer._toggle_segmentation_structure(exclude)
            if callable(cancel_job):
                cancel_job(exclude)
            settle(series_view, 80)

    for name in names:
        if name in viewer.get_active_segmentation_names():
            continue
        viewer._toggle_segmentation_structure(name)
        # Current slice is already contoured; stop the background worker immediately.
        if callable(cancel_job):
            cancel_job(name)
        # Drop volumetric mask after current-slice overlay is cached — frees RAM.
        try:
            series_view._structure_mask_by_name.pop(name, None)
        except Exception:
            pass
        settle(series_view, 80)
        gc.collect()
    settle(series_view, max(settle_ms, 800))
    ensure = getattr(series_view, "_ensure_segmentation_overlays_for_frame", None)
    if callable(ensure):
        ensure(viewer.current_image_index)
    settle(series_view, 500)
    return names


def prepare_series_view_for_grab(series_view: Any, *, settle_ms: int = 1000) -> None:
    """Force Series View on-screen and frontmost before ImageGrab / screencapture."""
    try:
        screen_w = int(series_view.winfo_screenwidth())
        screen_h = int(series_view.winfo_screenheight())
        width = min(1280, max(980, screen_w - 40))
        height = min(860, max(680, screen_h - 60))
        series_view.geometry(f"{width}x{height}+24+40")
    except Exception:
        pass
    try:
        series_view.deiconify()
        series_view.lift()
        series_view.attributes("-topmost", True)
        series_view.focus_force()
    except Exception:
        pass
    settle(series_view, settle_ms)
    try:
        series_view.update_idletasks()
        series_view.update()
    except Exception:
        pass


def grab_series_with_overlays(
    ctx: Any,
    series_view: Any,
    *dialogs: Any,
    shot: Any,
) -> Path:
    """Grab Series View alone, or Series View + open dialogs as a union bbox.

    When Screen Recording returns black frames (common under Cursor agents),
    falls back to an off-screen Series View composite for single-window shots.
    Set ANON_CAPTURE_OFFSCREEN=1 to force the off-screen path.
    """
    live_dialogs = [d for d in dialogs if d is not None]
    dest = ctx.dest(shot)
    settle_ms = max(getattr(ctx, "settle_ms", 400), 700)
    allow = getattr(ctx, "allow_placeholder", False)
    force_offscreen = os.environ.get("ANON_CAPTURE_OFFSCREEN", "").strip() in {"1", "true", "yes"}
    # SegmentedSeries must show real Series View chrome — never the off-screen mock.
    if getattr(shot, "id", "") == "Process_Harmonize_SegmentedSeries":
        force_offscreen = False
    if not live_dialogs:
        if force_offscreen:
            from docs_help.series_view_export import export_series_view_docs_shot

            return export_series_view_docs_shot(series_view, dest)
        return grab_widget(
            series_view,
            dest,
            settle_ms=settle_ms,
            allow_placeholder=allow,
            shot_id=shot.id,
        )
    return grab_widgets_union(
        [series_view, *live_dialogs],
        dest,
        settle_ms=settle_ms,
        allow_placeholder=allow,
        shot_id=shot.id,
    )


def grab_dialogs(
    ctx: Any,
    *dialogs: Any,
    shot: Any,
) -> Path:
    """Grab dialog(s) only — no Series View bleed-through.

    One dialog → window-ID grab. Two dialogs (Harmonize + prompt) → stacked
    window-ID composite on a flat background.
    """
    live = [d for d in dialogs if d is not None]
    if not live:
        raise RuntimeError("grab_dialogs requires at least one dialog")
    dest = ctx.dest(shot)
    settle_ms = max(getattr(ctx, "settle_ms", 400), 700)
    allow = getattr(ctx, "allow_placeholder", False)
    if len(live) == 1:
        return grab_widget(
            live[0],
            dest,
            settle_ms=settle_ms,
            allow_placeholder=allow,
            shot_id=shot.id,
        )
    return grab_stacked_windows(
        live[0],
        live[1],
        dest,
        settle_ms=settle_ms,
        allow_placeholder=allow,
        shot_id=shot.id,
        overlay_offset=(90, 110),
    )


def prepare_series_for_harmonize(
    ctx: Any,
    fixture: str,
    *,
    import_fixtures: Callable[..., None],
    clear_cache: bool = True,
) -> HarmonizeCaptureSession:
    """Import fixture, open Series View, optionally clear prior Harmonize cache."""
    import_fixtures(ctx, fixture)
    series_path = series_for_fixture(ctx.app.controller.model.images_dir(), fixture)
    if series_path is None:
        raise RuntimeError(f"No series for fixture {fixture!r}")
    series_view = open_series_view(ctx, series_path)
    if clear_cache:
        clear_series_analysis_cache(series_view)
    return HarmonizeCaptureSession(series_view=series_view, series_path=series_path)


def run_harmonize_to_results(
    session: HarmonizeCaptureSession,
    *,
    policy: BrainPromptPolicy,
    timeout_s: float = DEFAULT_HARMONIZE_TIMEOUT_S,
) -> Any:
    """Start Harmonize under ``policy`` and wait for a complete results table."""
    if policy is BrainPromptPolicy.CAPTURE:
        raise ValueError("Use capture_brain_prompt_over_harmonize for CAPTURE policy")
    with brain_prompt_policy(policy):
        session.harmonize_view = start_harmonize_from_series_view(session.series_view)
        wait_harmonize_results_ready(session.harmonize_view, timeout_s=timeout_s)
        fit_harmonize_results_for_capture(session.harmonize_view)
        settle(session.harmonize_view, 600)
    return session.harmonize_view


def capture_brain_prompt_over_harmonize(
    ctx: Any,
    session: HarmonizeCaptureSession,
    shot: Any,
    *,
    answer: bool = True,
    settle_before_grab_ms: int = 800,
) -> Path:
    """Grab Harmonize Description + brain Yes/No only (no Series View behind).

    Moves Series View off-screen so a screen-region grab cannot include it, then
    composites Harmonize + a stand-in prompt (native messageboxes are not
    window-ID-capturable).
    """
    title, message = brain_structures_prompt_copy()

    with brain_prompt_policy(BrainPromptPolicy.AUTO_NO):
        session.harmonize_view = start_harmonize_from_series_view(session.series_view)
    settle(session.harmonize_view, max(getattr(ctx, "settle_ms", 400), 700))
    try:
        session.harmonize_view.geometry(f"{getattr(session.harmonize_view, 'MIN_WIDTH', 1100)}x640")
    except Exception:
        pass
    settle(session.harmonize_view, 300)

    # Full-screen cover behind the dialogs so Series View cannot bleed into
    # ImageGrab fallbacks when screencapture -l is unavailable.
    cover = None
    try:
        sw = int(session.harmonize_view.winfo_screenwidth())
        sh = int(session.harmonize_view.winfo_screenheight())
        cover = ctk.CTkToplevel(session.harmonize_view.winfo_toplevel())
        cover.title("")
        cover.geometry(f"{sw}x{sh}+0+0")
        cover.configure(fg_color=("#F5F5F5", "#F5F5F5"))
        cover.attributes("-topmost", True)
        cover.lift()
    except Exception as exc:
        logger.warning("Brain-prompt cover window failed: %s", exc)
        cover = None

    # Keep Series View lowered under the cover (do not withdraw — destroys children).
    try:
        session.series_view.attributes("-topmost", False)
        session.series_view.lower()
    except Exception:
        pass

    dlg = show_brain_prompt_standin(session.harmonize_view, title=title, message=message)
    session.brain_prompt = dlg
    try:
        session.harmonize_view.geometry("+80+60")
        session.harmonize_view.lift()
        session.harmonize_view.attributes("-topmost", True)
        dlg.geometry("+200+160")
        dlg.lift()
        dlg.attributes("-topmost", True)
    except Exception:
        pass
    settle(session.harmonize_view, settle_before_grab_ms)
    settle(dlg, 300)

    try:
        path = grab_dialogs(ctx, session.harmonize_view, dlg, shot=shot)
    except Exception as exc:
        logger.warning("Stacked dialog grab failed (%s); union over cover", exc)
        path = grab_widgets_union(
            [session.harmonize_view, dlg],
            ctx.dest(shot),
            settle_ms=max(getattr(ctx, "settle_ms", 400), 700),
            allow_placeholder=getattr(ctx, "allow_placeholder", False),
            shot_id=shot.id,
        )
    close_toplevel(dlg)
    if cover is not None:
        close_toplevel(cover)
    cancel_harmonize_quietly(session.harmonize_view)
    return path


def close_harmonize_session(session: HarmonizeCaptureSession) -> None:
    """Best-effort teardown of Harmonize + Series View."""
    if session.brain_prompt is not None:
        close_toplevel(session.brain_prompt)
        session.brain_prompt = None
    if session.harmonize_view is not None:
        cancel_harmonize_quietly(session.harmonize_view, wait_s=3.0)
        close_toplevel(session.harmonize_view)
        session.harmonize_view = None
    close_toplevel(session.series_view)
