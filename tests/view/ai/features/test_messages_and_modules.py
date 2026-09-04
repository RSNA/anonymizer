"""Tests for AI Features view strings and tseg module boundaries."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from anonymizer.controller.ai.tseg import ml_env, readiness
from anonymizer.controller.ai.tseg.config import (
    apply_ai_features_preferences,
    clear_segmentation_mode_cache,
    get_ct_segmentation_mode,
    get_mr_segmentation_mode,
    persist_ai_features_preferences,
    set_ct_segmentation_mode,
    set_mr_segmentation_mode,
)
from anonymizer.utils.translate import _
from anonymizer.view.ai.features.availability import friendly_task_label
from anonymizer.view.ai.features.catalog import (
    AiFeatureId,
    feature_description,
    feature_summary,
    feature_title,
)

_LOCALES_ROOT = Path(__file__).resolve().parents[4] / "src" / "anonymizer" / "assets" / "locales"

_KEY_AI_MSGIDS = (
    "AI Features",
    "AI Features Setup",
    "Download models and choose Harmonize resolution for this workstation.",
    "Harmonize",
    "Slice Thickness",
    "Series Type Modifier",
    "Standardize SeriesDescription (CT/MR).",
)


def _po_msgstr(locale: str, msgid: str) -> str | None:
    po_path = _LOCALES_ROOT / locale / "LC_MESSAGES" / "messages.po"
    block_re = re.compile(
        rf'(?:^#, fuzzy\n)?msgid "{re.escape(msgid)}"\nmsgstr "(.*)"\n',
        re.M,
    )
    match = block_re.search(po_path.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def test_ml_env_and_readiness_modules_export_expected_symbols() -> None:
    assert callable(ml_env.sequential_ml_context)
    assert callable(readiness.anatomy_ct_ready)
    assert callable(readiness.weight_kind_ready)
    assert callable(readiness.download_segmentation_model)
    assert not hasattr(readiness, "get_runtime_status")
    assert readiness.TsWeightKind.ANATOMY.value == "anatomy"
    assert feature_title(AiFeatureId.HARMONIZE.value) == "Harmonize"


def test_feature_strings_use_gettext() -> None:
    assert _("Remove") == "Remove"
    assert feature_description(AiFeatureId.HARMONIZE.value) == "Standardize SeriesDescription (CT/MR)."
    assert feature_summary(AiFeatureId.HARMONIZE.value) == "RadLex series naming from anatomy."
    assert _("Downloading. This may take several minutes.").startswith("Downloading")
    assert _(
        "The downloaded models for this tool will be removed from disk. Are you sure?"
    ).startswith("The downloaded models")
    assert friendly_task_label(297) == "CT anatomy 3 mm"
    assert friendly_task_label(856) == "MR face 1.5 mm"
    assert "total" not in friendly_task_label(852).lower()
    assert "face_mr" not in friendly_task_label(856)


def test_segmentation_modes_persist_in_app_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from anonymizer.utils import app_state

    state_path = tmp_path / ".anonymizer_state.json"
    monkeypatch.setattr(app_state, "get_app_state_path", lambda: state_path)
    clear_segmentation_mode_cache()
    try:
        assert get_ct_segmentation_mode() == "3mm"
        set_ct_segmentation_mode("1.5mm")
        set_mr_segmentation_mode("6mm")
        persist_ai_features_preferences()

        clear_segmentation_mode_cache()
        apply_ai_features_preferences()
        assert get_ct_segmentation_mode() == "1.5mm"
        assert get_mr_segmentation_mode() == "6mm"
    finally:
        clear_segmentation_mode_cache()


@pytest.mark.parametrize("locale", ("de", "es", "fr"))
def test_ai_feature_msgids_translated_in_catalog(locale: str) -> None:
    for msgid in _KEY_AI_MSGIDS:
        msgstr = _po_msgstr(locale, msgid)
        assert msgstr is not None, f"{msgid!r} missing from {locale} catalog"
        assert msgstr.strip(), f"{msgid!r} has empty translation in {locale}"
        assert msgstr != msgid or locale == "en_US"
