#!/usr/bin/env python3
"""Live MVP integration: MCP HTTP server + Davidson CXR + optional MedGemma report.

Usage (anonymizer repo)::

  # Terminal-free overnight run (mocked OCR for speed unless --real-ocr):
  uv run python tests/mcp/run_mvp_live.py --port 8000

  # Real EasyOCR (slow first time):
  uv run python tests/mcp/run_mvp_live.py --real-ocr

  # Also load MedGemma and write a CXR report (needs local weights):
  uv run python tests/mcp/run_mvp_live.py --real-ocr --medgemma \\
      --medgemma-dir /path/to/medgemma_4b_it

Spawns ``rsna-anonymizer --mcp HOST:PORT``, drives create→import→strip→export,
writes a JSON summary under the project private dir, then tears the server down.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DAVIDSON_DCM = next(
    (
        REPO
        / "tests"
        / "controller"
        / "assets"
        / "test_dcm_files"
        / "davidson_cxr"
    ).glob("*.dcm")
)


def _tool_payload(result) -> dict:
    from anonymizer.mcp.api import parse_wire_text

    text = "".join(getattr(b, "text", "") or "" for b in (getattr(result, "content", None) or []))
    return parse_wire_text(text)


async def _mvp(url: str, storage_dir: Path, *, skip_ocr: bool) -> dict:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    summary: dict = {"steps": []}
    async with streamable_http_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {t.name for t in (await session.list_tools()).tools}
            assert "remove_pixel_phi" in tools and "export_series_preview" in tools

            storage_dir.mkdir(parents=True, exist_ok=True)
            created = _tool_payload(
                await session.call_tool(
                    "create_project",
                    {
                        "project_name": storage_dir.name,
                        "storage_dir": str(storage_dir),
                        "overwrite": True,
                    },
                )
            )
            assert created.get("ok"), created
            summary["steps"].append({"create_project": created.get("ok")})

            imported = _tool_payload(
                await session.call_tool("import_file", {"file_path": str(DAVIDSON_DCM)})
            )
            assert imported.get("ok") and imported.get("succeeded", 0) >= 1, imported
            summary["steps"].append(
                {
                    "import_file": {
                        "succeeded": imported.get("succeeded"),
                        "imported_modalities": (imported.get("project") or {}).get(
                            "imported_modalities"
                        ),
                    }
                }
            )

            inv = _tool_payload(await session.call_tool("list_inventory", {}))
            assert inv.get("ok") and inv.get("count", 0) >= 1, inv
            row = inv["series"][0]
            assert "series_path" not in row
            summary["patient_index"] = row.get("patient_index")
            summary["anon_patient_id"] = row.get("anon_patient_id")

            if skip_ocr:
                # Mark scanned by exporting with gate off, then user still gets a preview.
                preview = _tool_payload(
                    await session.call_tool(
                        "export_series_preview",
                        {
                            "patient": "1",
                            "series": "1",
                        },
                    )
                )
                summary["steps"].append({"remove_pixel_phi": "skipped (--skip-ocr)"})
            else:
                stripped = _tool_payload(
                    await session.call_tool(
                        "remove_pixel_phi",
                        {"series": "all"},
                    )
                )
                assert stripped.get("ok"), stripped
                summary["steps"].append(
                    {
                        "remove_pixel_phi": {
                            "status": stripped.get("status"),
                            "series_count": stripped.get("series_count"),
                            "pixel_phi_scanned": stripped.get("pixel_phi_scanned"),
                        }
                    }
                )
                preview = _tool_payload(
                    await session.call_tool(
                        "export_series_preview",
                        {"patient": "1", "series": "1"},
                    )
                )

            assert preview.get("ok"), preview
            preview_path = preview.get("preview_path")
            if not preview_path and preview.get("preview_base64"):
                import base64

                ext = ".jpg" if "jpeg" in str(preview.get("mime_type") or "") else ".png"
                out_img = storage_dir / "private" / f"mvp_preview{ext}"
                out_img.parent.mkdir(parents=True, exist_ok=True)
                out_img.write_bytes(base64.b64decode(preview["preview_base64"]))
                preview_path = str(out_img)
            summary["preview_path"] = preview_path
            summary["preview"] = {
                "width": preview.get("width"),
                "height": preview.get("height"),
                "modality": preview.get("modality"),
                "pixel_phi_scanned": preview.get("pixel_phi_scanned"),
            }
            summary["ok"] = True
    return summary


def _medgemma_report(preview_path: Path, model_dir: Path, device: str) -> str:
    from prototyping.medgemma_chat.infer import (
        generate_cxr_report,
        load_medgemma,
        require_ml,
        resolve_device,
    )

    torch_mod, AutoModel, AutoProcessor = require_ml()
    dev = resolve_device(device, torch_mod)
    model, processor = load_medgemma(model_dir, dev, torch_mod, AutoModel, AutoProcessor)
    return generate_cxr_report(
        model=model,
        processor=processor,
        device=dev,
        torch_mod=torch_mod,
        image_path=preview_path,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=Path.home() / "Documents" / "RSNA Anonymizer" / "MVP_LIVE",
    )
    parser.add_argument(
        "--skip-ocr",
        action="store_true",
        help="Skip remove_pixel_phi (export with require_pixel_phi_scanned=false)",
    )
    parser.add_argument(
        "--real-ocr",
        action="store_true",
        help="Run EasyOCR strip (default unless --skip-ocr)",
    )
    parser.add_argument("--medgemma", action="store_true", help="Generate MedGemma CXR report")
    parser.add_argument(
        "--medgemma-dir",
        type=Path,
        default=None,
        help="Local MedGemma weights directory (required with --medgemma)",
    )
    parser.add_argument("--device", default="auto", choices=("auto", "mps", "cpu", "cuda"))
    args = parser.parse_args()
    skip_ocr = args.skip_ocr or not args.real_ocr
    # Default: real OCR when --real-ocr; otherwise skip for speed unless user insists.
    if args.real_ocr:
        skip_ocr = False

    if args.medgemma and args.medgemma_dir is None:
        print("--medgemma requires --medgemma-dir /path/to/medgemma_4b_it", file=sys.stderr)
        return 2

    url = f"http://{args.host}:{args.port}/mcp"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "anonymizer.anonymizer",
            "--mcp",
            f"{args.host}:{args.port}",
        ],
        cwd=str(REPO),
    )
    try:
        time.sleep(2.5)
        if proc.poll() is not None:
            print("MCP server failed to start", file=sys.stderr)
            return 1
        print(f"MCP server pid={proc.pid} at {url}", flush=True)
        summary = asyncio.run(_mvp(url, args.storage_dir.expanduser().resolve(), skip_ocr=skip_ocr))
        print(json.dumps(summary, indent=2), flush=True)

        if args.medgemma:
            preview = Path(summary["preview_path"])
            print("Running MedGemma report…", flush=True)
            report = _medgemma_report(preview, args.medgemma_dir.expanduser().resolve(), args.device)
            report_path = preview.parent / "medgemma_report.txt"
            report_path.write_text(report, encoding="utf-8")
            print(report, flush=True)
            print(f"Wrote {report_path}", flush=True)
            summary["medgemma_report_path"] = str(report_path)

        out = args.storage_dir.expanduser().resolve() / "private" / "mcp_mvp_summary.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Summary: {out}", flush=True)
        return 0 if summary.get("ok") else 1
    finally:
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
