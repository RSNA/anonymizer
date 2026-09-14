"""Windows screenshot capture lab for docs_help.

Opens a CTk window (and a small dialog) and writes one PNG per grab method so
we can pick a path that captures the window chrome only — no desktop, no DWM
black resize margin, no edge-color trim.

    uv run python src/prototyping/ui/windows_shot.py
    uv run python src/prototyping/ui/windows_shot.py --auto

PNGs + report.txt land in ``docs/.capture_work/windows_shot_proto/``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

OUT_DIR = REPO_ROOT / "docs" / ".capture_work" / "windows_shot_proto"

from docs_help.platform.common import capture_bbox_imagegrab  # noqa: E402
from docs_help.platform.windows import (  # noqa: E402
    _SRCCOPY,
    _bitblt_screen,
    _capture_hwnd,
    _dwm_visible_rect,
    _find_hwnd,
    _hbitmap_to_image,
    _hwnd_from_winfo_id,
    _per_monitor_dpi,
    _printwindow_bitmap,
    _window_rect,
    capture_window,
    crop_box_for_visible_frame,
)


def _edge_stats(image: Image.Image, band: int = 4) -> dict[str, float]:
    """Mean luma of a 4px frame — flags desktop-white or DWM-black margins."""
    rgb = image.convert("RGB")
    w, h = rgb.size
    band = max(1, min(band, w // 4, h // 4))
    px = rgb.load()
    samples: list[float] = []

    def take(x: int, y: int) -> None:
        r, g, b = px[x, y]
        samples.append((r + g + b) / 3.0)

    for x in range(w):
        for y in list(range(band)) + list(range(h - band, h)):
            take(x, y)
    for y in range(band, h - band):
        for x in list(range(band)) + list(range(w - band, w)):
            take(x, y)
    mean = sum(samples) / len(samples)
    return {"mean_luma": round(mean, 1), "min_luma": round(min(samples), 1), "max_luma": round(max(samples), 1)}


def _ga_root(hwnd: int | None) -> int | None:
    if hwnd is None:
        return None
    try:
        from ctypes import windll
        from ctypes.wintypes import HWND

        GA_ROOT = 2
        root = int(windll.user32.GetAncestor(HWND(hwnd), GA_ROOT) or 0)
        return root or hwnd
    except Exception:
        return hwnd


def _hwnd_info(widget: Any) -> dict[str, Any]:
    raw = widget.winfo_id()
    parsed = _hwnd_from_winfo_id(raw)
    found = _find_hwnd(widget)
    ancestor = _ga_root(parsed)
    with _per_monitor_dpi():
        window = _window_rect(found) if found else None
        visible = _dwm_visible_rect(found) if found else None
    crop = crop_box_for_visible_frame(window, visible) if window and visible else None
    return {
        "winfo_id_type": type(raw).__name__,
        "winfo_id_repr": repr(raw)[:80],
        "parsed_winfo_id": parsed,
        "toplevel_hwnd": found,
        "GetAncestor_GA_ROOT": ancestor,
        "tk_geom": {
            "rootx": int(widget.winfo_rootx()),
            "rooty": int(widget.winfo_rooty()),
            "width": int(widget.winfo_width()),
            "height": int(widget.winfo_height()),
        },
        "GetWindowRect": window,
        "DWM_visible": visible,
        "crop_box": crop,
    }


def _windowdc_visible_blit(hwnd: int) -> Image.Image | None:
    """BitBlt the window DC at the DWM inset — window pixels, no desktop, no extra margin."""
    from ctypes import windll
    from ctypes.wintypes import HWND

    with _per_monitor_dpi():
        window = _window_rect(hwnd)
        visible = _dwm_visible_rect(hwnd)
        if window is None:
            return None
        crop = crop_box_for_visible_frame(window, visible) if visible else None
        if crop is None:
            left, top, width, height = 0, 0, window[2] - window[0], window[3] - window[1]
        else:
            left, top, right, bottom = crop
            width, height = right - left, bottom - top
        user32 = windll.user32
        gdi32 = windll.gdi32
        hwnd_dc = user32.GetWindowDC(HWND(hwnd))
        if not hwnd_dc:
            return None
        mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
        bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
        old = gdi32.SelectObject(mem_dc, bmp)
        try:
            ok = gdi32.BitBlt(mem_dc, 0, 0, width, height, hwnd_dc, left, top, _SRCCOPY)
            if not ok:
                return None
            return _hbitmap_to_image(gdi32, mem_dc, bmp, width, height)
        finally:
            gdi32.SelectObject(mem_dc, old)
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(HWND(hwnd), hwnd_dc)


def _methods(widget: Any) -> dict[str, Callable[[int], Image.Image | None]]:
    def printwindow_full(hwnd: int) -> Image.Image | None:
        with _per_monitor_dpi():
            window = _window_rect(hwnd)
            if window is None:
                return None
            return _printwindow_bitmap(hwnd, window)

    def printwindow_dwm_crop(hwnd: int) -> Image.Image | None:
        return _capture_hwnd(hwnd)

    def windowdc_dwm_inset(hwnd: int) -> Image.Image | None:
        return _windowdc_visible_blit(hwnd)

    def screen_dwm(hwnd: int) -> Image.Image | None:
        with _per_monitor_dpi():
            visible = _dwm_visible_rect(hwnd) or _window_rect(hwnd)
            if visible is None:
                return None
            return _bitblt_screen(visible)

    def screen_getwindowrect(hwnd: int) -> Image.Image | None:
        with _per_monitor_dpi():
            window = _window_rect(hwnd)
            if window is None:
                return None
            return _bitblt_screen(window)

    def imagegrab_tk_bbox(_hwnd: int) -> Image.Image | None:
        x = int(widget.winfo_rootx())
        y = int(widget.winfo_rooty())
        w = int(widget.winfo_width())
        h = int(widget.winfo_height())
        return capture_bbox_imagegrab((x, y, x + w, y + h))

    def docs_help_capture_window(hwnd: int) -> Image.Image | None:
        del hwnd
        return capture_window(widget, OUT_DIR / "_docs_help.png", widget.title())

    return {
        "printwindow_full": printwindow_full,
        "printwindow_dwm_crop": printwindow_dwm_crop,
        "windowdc_dwm_inset": windowdc_dwm_inset,
        "screen_dwm": screen_dwm,
        "screen_getwindowrect": screen_getwindowrect,
        "imagegrab_tk_bbox": imagegrab_tk_bbox,
        "docs_help_capture_window": docs_help_capture_window,
    }


def capture_widget(widget: Any, stem: str, out_dir: Path) -> dict[str, Any]:
    widget.update_idletasks()
    widget.update()
    try:
        widget.lift()
        widget.attributes("-topmost", True)
        widget.focus_force()
    except Exception:
        pass
    widget.update()

    info = _hwnd_info(widget)
    hwnd = info["toplevel_hwnd"]
    results: dict[str, Any] = {"info": info, "methods": {}}
    if hwnd is None:
        results["error"] = "HWND resolve failed"
        return results

    for name, fn in _methods(widget).items():
        try:
            image = fn(int(hwnd))
        except Exception as exc:
            results["methods"][name] = {"ok": False, "error": str(exc)}
            continue
        if image is None:
            results["methods"][name] = {"ok": False, "error": "None"}
            continue
        path = out_dir / f"{stem}__{name}.png"
        image.save(path)
        stats = _edge_stats(image)
        results["methods"][name] = {
            "ok": True,
            "path": str(path),
            "size": list(image.size),
            **stats,
        }
    return results


def _build_ui():
    import customtkinter as ctk

    ctk.set_appearance_mode("Light")
    root = ctk.CTk()
    root.title("Windows Shot Prototype")
    root.geometry("728x520+80+80")
    frame = ctk.CTkFrame(root)
    frame.pack(fill="both", expand=True, padx=16, pady=16)
    ctk.CTkLabel(frame, text="Welcome-sized CTk window", font=ctk.CTkFont(size=20)).pack(pady=(12, 8))
    ctk.CTkLabel(
        frame,
        text="Gray chrome should fill the PNG.\nBlack edge = DWM margin. White edge = desktop.",
        justify="left",
    ).pack(pady=8)
    ctk.CTkButton(frame, text="AI Features").pack(pady=8)

    dialog = ctk.CTkToplevel(root)
    dialog.title("Local Server")
    dialog.geometry("420x220+160+160")
    inner = ctk.CTkFrame(dialog)
    inner.pack(fill="both", expand=True, padx=12, pady=12)
    ctk.CTkLabel(inner, text="Address:  127.0.0.1").pack(anchor="w", pady=4)
    ctk.CTkLabel(inner, text="Port:     1045").pack(anchor="w", pady=4)
    ctk.CTkButton(inner, text="Ok", width=90).pack(anchor="e", pady=12)
    return root, dialog


def run(*, auto: bool) -> Path:
    if sys.platform != "win32":
        raise SystemExit("This prototype is Windows-only")
    out_dir = OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    root, dialog = _build_ui()
    root.update_idletasks()
    root.update()
    dialog.update_idletasks()
    dialog.update()

    def grab_and_write() -> None:
        report = {
            "app": capture_widget(root, "app", out_dir),
            "dialog": capture_widget(dialog, "dialog", out_dir),
        }
        path = out_dir / "report.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        lines = [f"Wrote {path}", ""]
        for group, payload in report.items():
            lines.append(f"## {group}")
            info = payload.get("info") or {}
            lines.append(f"  hwnd={info.get('toplevel_hwnd')} ancestor={info.get('GetAncestor_GA_ROOT')} winfo_id={info.get('winfo_id_repr')}")
            lines.append(f"  GetWindowRect={info.get('GetWindowRect')} DWM={info.get('DWM_visible')}")
            lines.append(f"  crop={info.get('crop_box')}")
            for name, meta in (payload.get("methods") or {}).items():
                if meta.get("ok"):
                    lines.append(
                        f"  {name}: {meta['size']} edge_mean={meta['mean_luma']} "
                        f"min={meta['min_luma']} max={meta['max_luma']}"
                    )
                else:
                    lines.append(f"  {name}: FAIL {meta.get('error')}")
            lines.append("")
        text = "\n".join(lines)
        (out_dir / "report.txt").write_text(text, encoding="utf-8")
        print(text)

    if auto:
        root.after(700, lambda: (grab_and_write(), root.destroy()))
    else:
        import customtkinter as ctk

        bar = ctk.CTkFrame(root)
        bar.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkButton(bar, text="Capture", command=grab_and_write).pack(side="left", padx=8)
        ctk.CTkButton(bar, text="Quit", command=root.destroy).pack(side="left")
    root.mainloop()
    return out_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auto", action="store_true", help="Grab once and exit")
    args = parser.parse_args(argv)
    run(auto=args.auto)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
