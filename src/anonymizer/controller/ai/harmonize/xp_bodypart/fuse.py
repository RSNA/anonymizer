"""Fuse Xp pixel body-part prediction with DICOM planar anatomy."""

from __future__ import annotations

from dataclasses import dataclass

from anonymizer.controller.ai.harmonize.xp_bodypart.labels import (
    coarse_region,
    is_extremity_fine_label,
    map_xp_label_to_planar_anatomy,
)
from anonymizer.controller.ai.harmonize.xp_bodypart.predict import XpBodypartPrediction
from anonymizer.utils.translate import _

_HIGH_CONF = 0.8
_MED_CONF = 0.5


@dataclass(frozen=True)
class AnatomyFusionResult:
    """Resolved planar anatomy after DICOM + optional pixel fusion."""

    label: str
    evidence: str
    source: str  # DICOM | pixel | fused
    pixel_label: str | None = None
    pixel_confidence: float | None = None
    dicom_label: str | None = None


def format_xp_bodypart_evidence(label: str, confidence: float) -> str:
    """Human-readable Xp-Bodypart evidence (matches CT classifier confidence style)."""
    return f"{label} · {confidence * 100.0:.2f}% " + _("confidence")


def fuse_planar_anatomy(
    *,
    dicom_label: str | None,
    dicom_evidence: str | None,
    pixel_pred: XpBodypartPrediction | None,
) -> AnatomyFusionResult:
    """Apply plan fusion rules; ``dicom_label`` None when metadata mapping failed."""
    dicom = (dicom_label or "").strip() or None
    dicom_ev = (dicom_evidence or "").strip()

    if pixel_pred is None:
        if not dicom:
            raise ValueError("Could not determine body part from DICOM or pixel model")
        return AnatomyFusionResult(
            label=dicom,
            evidence=dicom_ev or _("DICOM metadata"),
            source="DICOM",
            dicom_label=dicom,
        )

    pixel_raw = pixel_pred.label
    pixel_anatomy = map_xp_label_to_planar_anatomy(pixel_raw)
    conf = float(pixel_pred.confidence)
    pixel_ev = format_xp_bodypart_evidence(pixel_raw, conf)

    if not dicom:
        return AnatomyFusionResult(
            label=pixel_anatomy,
            evidence=pixel_ev,
            source="pixel",
            pixel_label=pixel_raw,
            pixel_confidence=conf,
        )

    # Extremities: keep fine-grain DICOM when pixel is coarse Extremities.
    if pixel_raw == "Extremities" and is_extremity_fine_label(dicom):
        joined = f"{dicom_ev}; {pixel_ev}" if dicom_ev else pixel_ev
        return AnatomyFusionResult(
            label=dicom,
            evidence=joined,
            source="fused",
            pixel_label=pixel_raw,
            pixel_confidence=conf,
            dicom_label=dicom,
        )

    if coarse_region(dicom) == coarse_region(pixel_raw):
        # Prefer DICOM fine text when both coarse-agree (e.g. Chest).
        label = dicom if dicom != "Extremities" else pixel_anatomy
        if pixel_raw == "Incomplete Chest":
            label = "Chest"
        joined = f"{dicom_ev}; {pixel_ev}" if dicom_ev else pixel_ev
        return AnatomyFusionResult(
            label=label,
            evidence=joined,
            source="fused",
            pixel_label=pixel_raw,
            pixel_confidence=conf,
            dicom_label=dicom,
        )

    if conf >= _HIGH_CONF:
        return AnatomyFusionResult(
            label=pixel_anatomy,
            evidence=_("{model} (overrides DICOM {dicom})").format(model=pixel_ev, dicom=dicom),
            source="pixel",
            pixel_label=pixel_raw,
            pixel_confidence=conf,
            dicom_label=dicom,
        )

    if conf >= _MED_CONF:
        secondary = _("; model secondary {label} · {pct:.2f}% confidence").format(
            label=pixel_raw, pct=conf * 100.0
        )
    else:
        secondary = ""
    return AnatomyFusionResult(
        label=dicom,
        evidence=f"{dicom_ev}{secondary}".strip("; "),
        source="DICOM",
        pixel_label=pixel_raw,
        pixel_confidence=conf,
        dicom_label=dicom,
    )
