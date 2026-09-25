"""Phase 2 MCP imaging: inventory, pixel-PHI strip (mocked OCR), preview export."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from anonymizer.mcp.session import SESSION
from anonymizer.mcp import tools as mcp_tools
from anonymizer.model.project import ProjectModel
from anonymizer.utils.translate import set_language_code

DAVIDSON = (
    Path(__file__).resolve().parent.parent
    / "controller"
    / "assets"
    / "test_dcm_files"
    / "davidson_cxr"
)
DAVIDSON_DCM = next(DAVIDSON.glob("*.dcm"))


@pytest.fixture(autouse=True)
def _isolated_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    set_language_code("en_US")
    monkeypatch.setattr(ProjectModel, "base_dir", staticmethod(lambda: tmp_path / "RSNA Anonymizer"))
    SESSION.close()
    yield
    SESSION.close()


def _open_project_with_davidson() -> dict:
    assert mcp_tools.create_project(project_name="MVPImaging", overwrite=True)["ok"]
    imported = mcp_tools.import_file(str(DAVIDSON_DCM))
    assert imported["ok"] is True
    assert imported["succeeded"] == 1
    return imported


def _fake_easyocr_results(_reader, pixels, *, modality=None):
    """Synthetic OCR boxes in corners (no real PHI strings that must stay out of MCP)."""
    h, w = pixels.shape[:2]
    # Minimal EasyOCR-like tuples: (bbox, text, conf)
    return [
        ([[0, 0], [40, 0], [40, 12], [0, 12]], "X", 0.99),
        ([[w - 40, h - 12], [w, h - 12], [w, h], [w - 40, h]], "Y", 0.99),
    ]


def test_list_inventory_after_davidson_import():
    _open_project_with_davidson()
    inv = mcp_tools.list_inventory()
    assert inv["ok"] is True
    assert inv["count"] >= 1
    row = inv["series"][0]
    assert row["anon_patient_id"]
    assert row["patient_index"] == 1
    assert row["series_index"] == 1
    assert row["instance_count"] >= 1
    assert row["pixel_phi_scanned"] is False
    assert row["modality"]
    assert "series_path" not in row
    assert "anon_series_uid" not in row
    assert "phi_" not in row
    assert "patient_name" not in row


def test_export_preview_allowed_without_pixel_phi_scan_by_default():
    """Preview export does not require remove_pixel_phi (no AI gate by default)."""
    _open_project_with_davidson()
    preview = mcp_tools.export_series_preview(patient="1", series="1")
    assert preview["ok"] is True
    import base64

    raw = base64.b64decode(preview["preview_base64"])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    assert preview["mime_type"] == "image/png"
    assert preview["width"] > 0 and preview["height"] > 0
    assert "series_path" not in preview


def test_export_preview_optional_gate_when_require_pixel_phi_scanned():
    _open_project_with_davidson()
    blocked = mcp_tools.export_series_preview(
        patient="1",
        series="1",
        require_pixel_phi_scanned=True,
    )
    assert blocked["ok"] is False
    assert "remove_pixel_phi" in blocked["error"].lower() or "scanned" in blocked["error"].lower()


def test_implicit_series_resolve_sole_inventory_for_remove_pixel_phi():
    """Omit anon_series_uid → sole imported series (researcher: 'that CXR')."""
    _open_project_with_davidson()
    fake_handle = MagicMock()
    fake_handle.reader = MagicMock()

    class _Outcome:
        status = "complete"
        message = "No burnt-in text detected"

    with (
        patch.object(SESSION, "ensure_ocr_reader", return_value=fake_handle),
        patch(
            "anonymizer.mcp.ops.apply_remove_pixel_phi_series",
            return_value=_Outcome(),
        ) as apply_mock,
        patch.object(
            SESSION.controller.anonymizer.model,
            "series_pixel_phi_scanned",
            return_value=True,
        ),
    ):
        result = mcp_tools.remove_pixel_phi(modality_hint="cxr")

    assert result["ok"] is True
    assert result["anon_series_uid"]
    apply_mock.assert_called_once()
    series_path = apply_mock.call_args.args[0]
    assert series_path.is_dir()


def test_invented_series_path_rejected():
    """MCP remove_pixel_phi rejects filesystem paths (selector-only API)."""
    from anonymizer.mcp import ops as ops

    _open_project_with_davidson()
    with pytest.raises(ops.HeadlessOpsError, match="not supported|filesystem|selectors"):
        ops.remove_pixel_phi(
            SESSION.controller,
            SESSION,
            series_path="/Users/michaelevans/Documents/RSNA Anonymizer/MCP_MVP/series/0001",
        )


@patch(
    "anonymizer.controller.ai.remove_pixel_phi._easyocr_readtext",
    side_effect=_fake_easyocr_results,
)
def test_remove_pixel_phi_then_export_davidson(mock_ocr: MagicMock):
    _open_project_with_davidson()

    # Avoid downloading real EasyOCR weights in unit tests.
    fake_handle = MagicMock()
    fake_handle.reader = MagicMock()
    with patch.object(SESSION, "ensure_ocr_reader", return_value=fake_handle):
        result = mcp_tools.remove_pixel_phi(
            patient="1", series="1", removal_mode="blackout"
        )

    assert result["ok"] is True
    assert result["status"] in {"ok", "complete"}
    assert result["pixel_phi_scanned"] is True
    # PHI/OCR digests must not appear in the MCP payload.
    blob = str(result)
    assert "PatientName" not in blob
    assert "detected_texts" not in blob
    assert "series_path" not in result
    mock_ocr.assert_called()

    inv2 = mcp_tools.list_inventory()
    assert inv2["series"][0]["pixel_phi_scanned"] is True

    preview = mcp_tools.export_series_preview(patient="1", series="1")
    assert preview["ok"] is True
    import base64

    assert base64.b64decode(preview["preview_base64"])[:8] == b"\x89PNG\r\n\x1a\n"
    assert "preview_path" not in preview
    assert "series_path" not in preview
    assert preview["pixel_phi_scanned"] is True


def test_remove_pixel_phi_response_omits_ocr_message_on_ok():
    """Guard: status ok must not echo format_remove_pixel_phi_series_message texts."""
    _open_project_with_davidson()
    fake_handle = MagicMock()
    fake_handle.reader = MagicMock()

    class _Outcome:
        status = "ok"
        message = "SECRET^PHI leaked in message"

    with (
        patch.object(SESSION, "ensure_ocr_reader", return_value=fake_handle),
        patch(
            "anonymizer.mcp.ops.apply_remove_pixel_phi_series",
            return_value=_Outcome(),
        ),
        patch.object(
            SESSION.controller.anonymizer.model,
            "series_pixel_phi_scanned",
            return_value=True,
        ),
    ):
        result = mcp_tools.remove_pixel_phi(patient="1", series="1")

    assert result["ok"] is True
    assert "SECRET^PHI" not in str(result)
    assert result["detail"] == "Burnt-in text removed from one or more instances"
