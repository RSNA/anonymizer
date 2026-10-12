"""Fuse CXp projection with DICOM XR view codes."""

from __future__ import annotations

from dataclasses import dataclass

from anonymizer.controller.ai.harmonize.cxp_view.labels import is_dicom_multiview
from anonymizer.controller.ai.harmonize.cxp_view.predict import CxpViewPrediction
from anonymizer.utils.translate import _

_HIGH_CONF = 0.8
_MED_CONF = 0.5


@dataclass(frozen=True)
class ViewFusionResult:
    """Resolved XR view after DICOM + optional pixel fusion."""

    view_code: str
    evidence: str
    source: str  # DICOM | pixel | fused
    pixel_view_code: str | None = None
    pixel_view_confidence: float | None = None
    rotation_label: str | None = None
    rotation_confidence: float | None = None
    dicom_view_code: str | None = None


def format_cxp_projection_evidence(projection: str, confidence: float) -> str:
    """Human-readable CXp projection evidence (CT-style confidence)."""
    return f"{projection} · {confidence * 100.0:.2f}% " + _("confidence")


def format_cxp_rotation_evidence(rotation: str, confidence: float) -> str:
    """Human-readable CXp rotation evidence."""
    return f"{rotation} · {confidence * 100.0:.2f}% " + _("confidence")


def fuse_xr_view(
    *,
    dicom_view: str | None,
    dicom_evidence: str | None,
    pixel_pred: CxpViewPrediction | None,
) -> ViewFusionResult:
    """Fuse DICOM view with pixel projection; never override 2V/3V from pixels."""
    dicom = (dicom_view or "").strip() or None
    dicom_ev = (dicom_evidence or "").strip()

    if pixel_pred is None:
        return ViewFusionResult(
            view_code=dicom or "",
            evidence=dicom_ev or (_("DICOM metadata") if dicom else ""),
            source="DICOM",
            dicom_view_code=dicom,
        )

    pixel_code = pixel_pred.playbook_view_code
    conf = float(pixel_pred.projection_confidence)
    pixel_ev = format_cxp_projection_evidence(pixel_pred.projection, conf)
    rot = pixel_pred.rotation
    rot_conf = float(pixel_pred.rotation_confidence)

    if is_dicom_multiview(dicom):
        kept = _("kept DICOM multiview")
        evidence = f"{dicom_ev}; {pixel_ev} ({kept})" if dicom_ev else f"{pixel_ev} ({kept})"
        return ViewFusionResult(
            view_code=dicom or "",
            evidence=evidence,
            source="DICOM",
            pixel_view_code=pixel_code,
            pixel_view_confidence=conf,
            rotation_label=rot,
            rotation_confidence=rot_conf,
            dicom_view_code=dicom,
        )

    if not dicom:
        return ViewFusionResult(
            view_code=pixel_code,
            evidence=pixel_ev,
            source="pixel",
            pixel_view_code=pixel_code,
            pixel_view_confidence=conf,
            rotation_label=rot,
            rotation_confidence=rot_conf,
        )

    if dicom == pixel_code:
        joined = f"{dicom_ev}; {pixel_ev}" if dicom_ev else pixel_ev
        return ViewFusionResult(
            view_code=dicom,
            evidence=joined,
            source="fused",
            pixel_view_code=pixel_code,
            pixel_view_confidence=conf,
            rotation_label=rot,
            rotation_confidence=rot_conf,
            dicom_view_code=dicom,
        )

    if conf >= _HIGH_CONF:
        return ViewFusionResult(
            view_code=pixel_code,
            evidence=_("{model} (overrides DICOM {dicom})").format(model=pixel_ev, dicom=dicom),
            source="pixel",
            pixel_view_code=pixel_code,
            pixel_view_confidence=conf,
            rotation_label=rot,
            rotation_confidence=rot_conf,
            dicom_view_code=dicom,
        )

    if conf >= _MED_CONF:
        secondary = _("; model secondary {label} · {pct:.2f}% confidence").format(
            label=pixel_code, pct=conf * 100.0
        )
    else:
        secondary = ""
    return ViewFusionResult(
        view_code=dicom,
        evidence=f"{dicom_ev}{secondary}".strip("; "),
        source="DICOM",
        pixel_view_code=pixel_code,
        pixel_view_confidence=conf,
        rotation_label=rot,
        rotation_confidence=rot_conf,
        dicom_view_code=dicom,
    )
