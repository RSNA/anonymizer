#!/usr/bin/env python3
"""Live MVP integration: MCP HTTP server + Davidson CXR + optional MedGemma report.

Spawns ``python -m anonymizer.anonymizer --mcp HOST:PORT``, waits until that
process accepts TCP, drives create→import→strip→export, writes a JSON summary,
then stops the server.

Run from the repo root in one terminal only::

  cd /Users/michaelevans/CODE/anonymizer
  lsof -tiTCP:8000 -sTCP:LISTEN | xargs kill 2>/dev/null || true
  uv run python tests/mcp/run_mvp_live.py --port 8000

Wait for ``MCP server listening`` (cold import can take several minutes).
Do not Ctrl-C during that wait. Do not start another MCP on the same port.

With EasyOCR::

  uv run python tests/mcp/run_mvp_live.py --port 8000 --real-ocr

With MedGemma after export::

  uv run python tests/mcp/run_mvp_live.py --port 8000 --medgemma \\
      --medgemma-dir /path/to/medgemma_4b_it
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
REPO = _HERE.parents[1]


def _load_wait_for_mcp_tcp():
    """Load sibling ``http_ready.py`` without requiring ``tests`` on ``sys.path``."""
    path = _HERE / "http_ready.py"
    spec = importlib.util.spec_from_file_location("mcp_http_ready", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.wait_for_mcp_tcp


wait_for_mcp_tcp = _load_wait_for_mcp_tcp()


def _davidson_dcm() -> Path:
    """Resolve the Davidson CXR fixture used by the live MVP."""
    folder = (
        REPO
        / "tests"
        / "controller"
        / "assets"
        / "test_dcm_files"
        / "davidson_cxr"
    )
    matches = sorted(folder.glob("*.dcm"))
    if not matches:
        raise FileNotFoundError(f"No *.dcm under {folder}")
    return matches[0]


def _port_in_use(host: str, port: int) -> bool:
    """Return True if something already accepts TCP on host:port."""
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _tool_payload(result) -> dict:
    from anonymizer.mcp.api import parse_wire_text

    text = "".join(getattr(b, "text", "") or "" for b in (getattr(result, "content", None) or []))
    payload = parse_wire_text(text)
    # Preview image is MCP ImageContent (base64 stripped from wire text).
    for block in getattr(result, "content", None) or []:
        data = getattr(block, "data", None)
        mime = getattr(block, "mime_type", None) or getattr(block, "mimeType", None)
        if data and (getattr(block, "type", None) == "image" or mime):
            payload["preview_base64"] = data
            if mime:
                payload["mime_type"] = mime
            break
    return payload


def _require(ok: bool, payload: dict, step: str) -> None:
    """Raise with the tool payload when a live step fails."""
    if not ok:
        raise RuntimeError(f"{step} failed: {json.dumps(payload, indent=2, default=str)}")


async def _mvp(url: str, storage_dir: Path, *, skip_ocr: bool, dcm: Path) -> dict:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    summary: dict = {"steps": []}
    async with streamable_http_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {t.name for t in (await session.list_tools()).tools}
            if "remove_pixel_phi" not in tools or "export_series_preview" not in tools:
                raise RuntimeError(f"MCP tool catalog missing MVP tools: {sorted(tools)}")

            storage_dir.mkdir(parents=True, exist_ok=True)
            defaults = _tool_payload(
                await session.call_tool("project_settings_defaults", {})
            )
            _require(bool(defaults.get("ok")), defaults, "project_settings_defaults")
            if "configuration_confirmation" not in (defaults.get("help") or {}):
                raise RuntimeError(
                    "project_settings_defaults missing help.configuration_confirmation: "
                    f"{json.dumps(defaults, indent=2, default=str)}"
                )
            summary["steps"].append({"project_settings_defaults": True})

            # project_name: letters/digits/space/hyphen/period only (no underscore).
            prepared = _tool_payload(
                await session.call_tool(
                    "create_project",
                    {
                        "project_name": "MVP LIVE",
                        "storage_dir": str(storage_dir),
                        "overwrite": True,
                        "confirm": False,
                    },
                )
            )
            _require(
                prepared.get("status") == "confirmation_required"
                and prepared.get("created") is False,
                prepared,
                "create_project prepare",
            )
            created = _tool_payload(
                await session.call_tool(
                    "create_project",
                    {
                        "project_name": "MVP LIVE",
                        "confirm": True,
                        "revision": prepared.get("revision"),
                    },
                )
            )
            _require(bool(created.get("ok")), created, "create_project confirm")
            summary["steps"].append({"create_project": True})

            imported = _tool_payload(
                await session.call_tool("import_file", {"file_path": str(dcm)})
            )
            _require(
                bool(imported.get("ok")) and int(imported.get("succeeded") or 0) >= 1,
                imported,
                "import_file",
            )
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
            _require(
                bool(inv.get("ok")) and int(inv.get("count") or 0) >= 1,
                inv,
                "list_inventory",
            )
            row = inv["series"][0]
            if "series_path" in row:
                raise RuntimeError("list_inventory leaked series_path")
            summary["patient_index"] = row.get("patient_index")
            summary["anon_patient_id"] = row.get("anon_patient_id")

            if skip_ocr:
                preview = _tool_payload(
                    await session.call_tool(
                        "export_series_preview",
                        {"patient": "1", "series": "1"},
                    )
                )
                summary["steps"].append({"remove_pixel_phi": "skipped"})
            else:
                stripped = _tool_payload(
                    await session.call_tool("remove_pixel_phi", {"series": "all"})
                )
                _require(bool(stripped.get("ok")), stripped, "remove_pixel_phi")
                if stripped.get("status") not in {"ok", None}:
                    raise RuntimeError(
                        f"remove_pixel_phi status={stripped.get('status')!r}: "
                        f"{json.dumps(stripped, indent=2, default=str)}"
                    )
                preview = _tool_payload(
                    await session.call_tool(
                        "export_series_preview",
                        {"patient": "1", "series": "1"},
                    )
                )
                # Batch remove_pixel_phi wire omits pixel_phi_scanned; preview is SSOT.
                scanned = bool(preview.get("pixel_phi_scanned"))
                if not scanned:
                    raise RuntimeError(
                        "export_series_preview.pixel_phi_scanned is false after "
                        f"remove_pixel_phi: {json.dumps(preview, indent=2, default=str)}"
                    )
                summary["steps"].append(
                    {
                        "remove_pixel_phi": {
                            "status": stripped.get("status"),
                            "series_count": stripped.get("series_count"),
                            "pixel_phi_scanned": scanned,
                        }
                    }
                )

            _require(bool(preview.get("ok")), preview, "export_series_preview")
            preview_path = preview.get("preview_path")
            if not preview_path and preview.get("preview_base64"):
                import base64

                raw_b64 = preview["preview_base64"]
                ext = ".jpg" if "jpeg" in str(preview.get("mime_type") or "") else ".png"
                out_img = storage_dir / "private" / f"mvp_preview{ext}"
                out_img.parent.mkdir(parents=True, exist_ok=True)
                out_img.write_bytes(base64.b64decode(raw_b64))
                preview_path = str(out_img)
            summary["preview_path"] = preview_path
            summary["preview"] = {
                "width": preview.get("width"),
                "height": preview.get("height"),
                "modality": preview.get("modality"),
                "pixel_phi_scanned": preview.get("pixel_phi_scanned"),
                "image_attached": bool(preview.get("preview_base64"))
                or preview.get("image") == "attached",
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


def _stop_server(proc: subprocess.Popen) -> None:
    """SIGINT the child, then kill if it ignores shutdown."""
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _tail_log(log_path: Path, *, max_lines: int = 80) -> str:
    """Return the last lines of the server log for failure messages."""
    if not log_path.is_file():
        return "(no server log)"
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:]) or "(empty server log)"


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
        help="Skip remove_pixel_phi",
    )
    parser.add_argument(
        "--real-ocr",
        action="store_true",
        help="Run EasyOCR strip (default is skip OCR for speed)",
    )
    parser.add_argument("--medgemma", action="store_true", help="Generate MedGemma CXR report")
    parser.add_argument(
        "--medgemma-dir",
        type=Path,
        default=None,
        help="Local MedGemma weights directory (required with --medgemma)",
    )
    parser.add_argument("--device", default="auto", choices=("auto", "mps", "cpu", "cuda"))
    parser.add_argument(
        "--ready-timeout",
        type=float,
        default=300.0,
        help="Seconds to wait for MCP TCP accept (default 300)",
    )
    args = parser.parse_args()
    skip_ocr = not args.real_ocr or args.skip_ocr

    if args.medgemma and args.medgemma_dir is None:
        print("--medgemma requires --medgemma-dir /path/to/medgemma_4b_it", file=sys.stderr)
        return 2

    try:
        dcm = _davidson_dcm()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if _port_in_use(args.host, args.port):
        print(
            f"Port {args.host}:{args.port} is already in use. "
            f"Stop that process first:\n"
            f"  lsof -tiTCP:{args.port} -sTCP:LISTEN | xargs kill",
            file=sys.stderr,
        )
        return 1

    storage = args.storage_dir.expanduser().resolve()
    storage.mkdir(parents=True, exist_ok=True)
    # Keep the server log outside project private/ — create_project overwrite
    # deletes that tree and would unlink a log opened under private/.
    log_path = storage.parent / f"{storage.name}_mcp_server.log"

    url = f"http://{args.host}:{args.port}/mcp"
    print(
        f"Starting MCP on {args.host}:{args.port} "
        f"(wait up to {args.ready_timeout:.0f}s; log={log_path})",
        flush=True,
    )
    log_fh = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "anonymizer.anonymizer",
            "--mcp",
            f"{args.host}:{args.port}",
        ],
        cwd=str(REPO),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
    )
    try:
        try:
            wait_for_mcp_tcp(
                args.host,
                args.port,
                proc,
                timeout_s=args.ready_timeout,
            )
        except (RuntimeError, TimeoutError) as exc:
            print(str(exc), file=sys.stderr)
            print("--- server log ---", file=sys.stderr)
            log_fh.flush()
            print(_tail_log(log_path), file=sys.stderr)
            return 1

        # Brief settle: uvicorn may accept TCP before the MCP app is mounted.
        time.sleep(0.5)
        if proc.poll() is not None:
            print(
                f"MCP server exited after listen (code={proc.returncode})",
                file=sys.stderr,
            )
            print("--- server log ---", file=sys.stderr)
            log_fh.flush()
            print(_tail_log(log_path), file=sys.stderr)
            return 1

        print(f"MCP server listening pid={proc.pid} at {url}", flush=True)
        try:
            summary = asyncio.run(_mvp(url, storage, skip_ocr=skip_ocr, dcm=dcm))
        except Exception as exc:
            print(f"MVP client failed: {exc}", file=sys.stderr)
            print("--- server log ---", file=sys.stderr)
            log_fh.flush()
            print(_tail_log(log_path), file=sys.stderr)
            return 1

        print(json.dumps(summary, indent=2), flush=True)

        if args.medgemma:
            preview = Path(summary["preview_path"])
            print("Running MedGemma report…", flush=True)
            report = _medgemma_report(
                preview, args.medgemma_dir.expanduser().resolve(), args.device
            )
            report_path = preview.parent / "medgemma_report.txt"
            report_path.write_text(report, encoding="utf-8")
            print(report, flush=True)
            print(f"Wrote {report_path}", flush=True)
            summary["medgemma_report_path"] = str(report_path)

        out = storage / "private" / "mcp_mvp_summary.json"
        out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"Summary: {out}", flush=True)
        return 0 if summary.get("ok") else 1
    finally:
        _stop_server(proc)
        log_fh.close()


if __name__ == "__main__":
    raise SystemExit(main())
