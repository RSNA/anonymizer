"""MCP MVP end-to-end: create → import Davidson → strip pixel PHI → export preview.

Runs against an in-process tool stack (no HTTP) for CI, and optionally against a
live ``rsna-anonymizer --mcp`` HTTP server via ``pytest -m mcp_e2e``.

Real EasyOCR is opt-in via ``pytest -m ocr_integration`` (slow; downloads weights).
Default path mocks OCR like ``test_imaging_phase2``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from anonymizer.mcp import api as mcp_tools
from anonymizer.mcp.session import SESSION
from anonymizer.model.project import ProjectModel
from anonymizer.utils.translate import set_language_code
from tests.mcp.http_ready import wait_for_mcp_tcp
from tests.mcp.job_poll import await_job
from tests.mcp.project_create import confirm_create

DAVIDSON = (
    Path(__file__).resolve().parent.parent
    / "controller"
    / "assets"
    / "test_dcm_files"
    / "davidson_cxr"
)
DAVIDSON_DCM = next(DAVIDSON.glob("*.dcm"))


@pytest.fixture
def mvp_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    set_language_code("en_US")
    monkeypatch.setattr(ProjectModel, "base_dir", staticmethod(lambda: tmp_path / "RSNA Anonymizer"))
    SESSION.close()
    yield tmp_path
    SESSION.close()


def _fake_easyocr(_reader, pixels, *, modality=None, overrides=None):
    del overrides  # match _easyocr_readtext; unused in the fake
    h, w = pixels.shape[:2]
    return [
        ([[0, 0], [30, 0], [30, 10], [0, 10]], "X", 0.9),
        ([[w - 30, h - 10], [w, h - 10], [w, h], [w - 30, h]], "Y", 0.9),
    ]


def test_mvp_create_import_strip_export_davidson(mvp_store: Path):
    """Full researcher MVP path with mocked OCR (fast, default CI)."""
    created = confirm_create(
        mcp_tools.create_project,
        project_name="MVP-E2E",
        overwrite=True,
    )
    assert created["ok"] is True

    imported = mcp_tools.import_file(str(DAVIDSON_DCM))
    assert imported["ok"] and imported["succeeded"] == 1
    assert imported["project"]["imported_modalities"]

    inv = mcp_tools.list_inventory()
    assert inv["ok"] and inv["count"] >= 1
    assert inv["series"][0]["patient_index"] == 1
    assert "series_path" not in inv["series"][0]

    fake_handle = MagicMock()
    fake_handle.reader = MagicMock()
    with (
        patch.object(SESSION, "ensure_ocr_reader", return_value=fake_handle),
        patch(
            "anonymizer.controller.ai.embedded_phi.pixel.detect_text._easyocr_readtext",
            side_effect=_fake_easyocr,
        ),
    ):
        stripped = await_job(
            mcp_tools.remove_pixel_phi(series="all"), mcp_tools.job_status
        )

    assert stripped["ok"] is True
    assert stripped.get("status") in {"ok", "complete", "partial"} or stripped.get(
        "pixel_phi_scanned"
    ) is True
    assert "SECRET" not in json.dumps(stripped)
    assert "series_path" not in stripped

    preview = mcp_tools.export_series_preview(patient="1", series="1")
    assert preview["ok"] is True
    import base64

    raw = base64.b64decode(preview["preview_base64"])
    assert len(raw) > 1000
    assert preview["mime_type"] == "image/png"
    assert "preview_path" not in preview
    assert "series_path" not in preview
    assert preview["modality"]

@pytest.mark.ocr_integration
def test_mvp_remove_pixel_phi_real_ocr_davidson(mvp_store: Path):
    """Opt-in: real EasyOCR on Davidson CXR (may download OCR weights)."""
    assert confirm_create(
        mcp_tools.create_project,
        project_name="MVP-OCR",
        overwrite=True,
    )["ok"]
    assert mcp_tools.import_file(str(DAVIDSON_DCM))["succeeded"] == 1
    result = await_job(mcp_tools.remove_pixel_phi(series="all"), mcp_tools.job_status)
    assert result["ok"] is True
    # Batch wire returns status/series_count; scanned flag is on inventory/preview.
    assert result.get("status") in {"ok", "complete", "partial"}
    assert int(result.get("series_count") or 0) >= 1
    preview = mcp_tools.export_series_preview(patient="1", series="1")
    assert preview["ok"] is True
    assert preview.get("pixel_phi_scanned") is True
    import base64

    assert len(base64.b64decode(preview["preview_base64"])) > 1000
    assert "preview_path" not in preview


@pytest.mark.mcp_e2e
def test_mvp_http_server_davidson(tmp_path: Path):
    """Spawn ``rsna-anonymizer --mcp HOST:PORT`` and drive tools over HTTP."""
    import asyncio
    import signal

    pytest.importorskip("mcp")
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    store = tmp_path / "RSNA Anonymizer"
    store.mkdir()
    port = 8765
    url = f"http://127.0.0.1:{port}/mcp"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "anonymizer.anonymizer",
            "--mcp",
            f"127.0.0.1:{port}",
        ],
        cwd=str(Path(__file__).resolve().parents[2]),
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        try:
            wait_for_mcp_tcp("127.0.0.1", port, proc, timeout_s=180.0)
        except (RuntimeError, TimeoutError) as exc:
            out = proc.stdout.read() if proc.stdout else ""
            pytest.fail(f"{exc}\n{out}")

        async def _drive() -> None:
            async with streamable_http_client(url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    names = {t.name for t in tools.tools}
                    assert "export_series_preview" in names
                    assert "remove_pixel_phi" in names

                    proj_dir = store / "HTTP_MVP"
                    proj_dir.mkdir()
                    # project_name: letters/digits/space/hyphen/period only (no underscore).
                    prepared = await session.call_tool(
                        "create_project",
                        {
                            "project_name": "HTTP MVP",
                            "storage_dir": str(proj_dir),
                            "overwrite": True,
                            "confirm": False,
                        },
                    )
                    prepared_text = "".join(
                        getattr(b, "text", "") or "" for b in (prepared.content or [])
                    )
                    prepared_payload = json.loads(prepared_text)
                    assert prepared_payload["status"] == "confirmation_required"
                    assert prepared_payload["created"] is False

                    created = await session.call_tool(
                        "create_project",
                        {
                            "project_name": "HTTP MVP",
                            "confirm": True,
                            "revision": prepared_payload["revision"],
                        },
                    )
                    text = "".join(getattr(b, "text", "") or "" for b in (created.content or []))
                    assert "ok" in text.lower()
                    assert not text.lower().startswith("error:")

                    imported = await session.call_tool(
                        "import_file", {"file_path": str(DAVIDSON_DCM)}
                    )
                    itext = "".join(
                        getattr(b, "text", "") or "" for b in (imported.content or [])
                    )
                    assert "succeeded" in itext

                    inv = await session.call_tool("list_inventory", {})
                    inv_text = "".join(getattr(b, "text", "") or "" for b in (inv.content or []))
                    assert "patient_index" in inv_text
                    assert "series_path" not in inv_text

        asyncio.run(_drive())
    finally:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
