"""De-identification option → AI feature map and readiness gates."""

import pytest

from anonymizer.model.project import AT_INGEST
from anonymizer.utils.dicom import DeidMethodCode
from anonymizer.view.ai.features import catalog
from anonymizer.view.ai.features.catalog import (
    AiFeatureId,
    ai_feature_for_deid_option,
    deid_option_ready,
)


def test_cleaning_options_map_to_features() -> None:
    """Cleaning options map to their executing feature; graphics/ingest to none."""
    assert ai_feature_for_deid_option(DeidMethodCode.CLEAN_PIXEL_DATA) is AiFeatureId.EMBEDDED_PHI
    assert ai_feature_for_deid_option(DeidMethodCode.CLEAN_STRUCTURED_CONTENT) is AiFeatureId.EMBEDDED_PHI
    assert ai_feature_for_deid_option(DeidMethodCode.CLEAN_DESCRIPTORS) is AiFeatureId.EMBEDDED_PHI
    assert ai_feature_for_deid_option(DeidMethodCode.CLEAN_VISUAL_FEATURES) is AiFeatureId.FACE_BLUR
    assert ai_feature_for_deid_option(DeidMethodCode.CLEAN_GRAPHICS) is None
    for code in AT_INGEST:
        assert ai_feature_for_deid_option(code) is None


def test_ingest_options_always_ready_and_graphics_never() -> None:
    """Ingest options need no download; never-executed options stay unselectable."""
    for code in AT_INGEST:
        assert deid_option_ready(code)
    assert not deid_option_ready(DeidMethodCode.CLEAN_GRAPHICS)


def test_cleaning_readiness_follows_feature_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cleaning readiness mirrors the controller feature-availability predicates."""
    monkeypatch.setattr(catalog.feature_gates, "embedded_phi_allowed", lambda: True)
    monkeypatch.setattr(catalog.feature_gates, "report_text_phi_ready", lambda: False)
    monkeypatch.setattr(catalog.feature_gates, "face_blur_allowed", lambda: True)
    assert deid_option_ready(DeidMethodCode.CLEAN_PIXEL_DATA)
    assert not deid_option_ready(DeidMethodCode.CLEAN_STRUCTURED_CONTENT)
    assert not deid_option_ready(DeidMethodCode.CLEAN_DESCRIPTORS)
    assert deid_option_ready(DeidMethodCode.CLEAN_VISUAL_FEATURES)
