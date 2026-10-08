"""Fit-width PDF / page canvas: PHI overlays, hover, draw Blackout/Exclude zones."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import Misc

import customtkinter as ctk
from PIL import Image, ImageTk

from anonymizer.controller.ai.embedded_phi.report.encapsulated_pdf import render_pdf_pages
from anonymizer.controller.ai.embedded_phi.report.hits import ReportHit
from anonymizer.controller.series_overlay import UserRectangle
from anonymizer.utils.translate import _
from anonymizer.view.common.ctk_safe import dispose_photo_image
from anonymizer.view.common.tooltip import MotionTooltipController
from anonymizer.view.reports.entity_colors import entity_color_hex, entity_label_display

_EXCLUDE_DASH = (8, 6)
_BLACKOUT_OUTLINE = "#cccccc"
_PENDING_OUTLINE = "#00ffff"
# Canvas inset left of the page image (matches create_image x=4).
_PAGE_X = 4


class PdfPageView(ctk.CTkFrame):
    """Scrollable fit-width page viewer with PHI overlays and zone drawing."""

    def __init__(
        self,
        master: Misc,
        *,
        on_toggle_hit: Callable[[str], None] | None = None,
        on_delete_exclude: Callable[[int, int], bool] | None = None,
        on_pending_rects: Callable[[], None] | None = None,
        on_pages_ready: Callable[[], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self._on_toggle_hit = on_toggle_hit
        self._on_delete_exclude = on_delete_exclude
        self._on_pending_rects = on_pending_rects
        self._on_pages_ready = on_pages_ready
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Page-white canvas — avoid black letterbox gutters around the PDF.
        self._canvas = tk.Canvas(self, highlightthickness=0, bg="#ffffff")
        self._vscroll = ctk.CTkScrollbar(self, orientation="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vscroll.set)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._vscroll.grid(row=0, column=1, sticky="ns")

        self._photos: list[ImageTk.PhotoImage] = []
        self._page_pils: list[Image.Image] = []
        self._page_offsets: list[int] = []  # canvas y of each page top
        self._page_heights: list[int] = []
        self._display_width = 0
        self._content_height = 0
        self._scale = 1.0  # display_px / page_user_unit (top-left space)
        self._page_widths_u: list[float] = []
        self._hits: list[ReportHit] = []
        self._excluded_keys: set[str] = set()
        self._exclude_rects: list[UserRectangle] = []
        self._blackout_rects: list[UserRectangle] = []
        self._pending: list[UserRectangle] = []
        self._draw_start: tuple[int, int] | None = None
        self._draw_rect_id: int | None = None
        self._placeholder = _("No PDF pages to display.")
        self._refit_retries = 0
        self._suspend_configure_refit = False

        self._canvas.bind("<Configure>", self._on_configure)
        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._bind_mousewheel()
        self._hover = MotionTooltipController(self._canvas, self._hover_text, parent=self.winfo_toplevel())
        self._hover.bind()

    def _bind_mousewheel(self) -> None:
        for widget in (self, self._canvas):
            widget.bind("<MouseWheel>", self._on_mousewheel, add="+")
            widget.bind("<Button-4>", self._on_mousewheel, add="+")
            widget.bind("<Button-5>", self._on_mousewheel, add="+")

    def _on_mousewheel(self, event: tk.Event) -> str:
        """Scroll the page canvas (macOS MouseWheel + X11 Button-4/5)."""
        num = getattr(event, "num", None)
        delta = int(getattr(event, "delta", 0) or 0)
        if num == 4 or delta > 0:
            steps = -1 if abs(delta) < 120 else int(-delta / 120)
            self._canvas.yview_scroll(steps or -1, "units")
        elif num == 5 or delta < 0:
            steps = 1 if abs(delta) < 120 else int(-delta / 120)
            self._canvas.yview_scroll(steps or 1, "units")
        return "break"

    def clear(self) -> None:
        self._canvas.delete("all")
        for photo in self._photos:
            dispose_photo_image(self, photo)
        self._photos.clear()
        self._page_pils.clear()
        self._page_offsets.clear()
        self._page_heights.clear()

    def first_page_pil_size(self) -> tuple[int, int] | None:
        """Raster size of page 0 (before display fit), or None."""
        if not self._page_pils:
            return None
        p = self._page_pils[0]
        return p.width, p.height

    def first_page_aspect(self) -> float | None:
        """height / width of page 0, or None."""
        size = self.first_page_pil_size()
        if size is None or size[0] <= 0:
            return None
        return size[1] / float(size[0])

    def page_content_size(self) -> tuple[int, int] | None:
        """Current fit-width display size of page stack content (w, h), or None."""
        if not self._page_heights or self._display_width <= 0:
            return None
        return self._display_width + _PAGE_X, self._content_height

    def show_pdf_bytes(
        self,
        data: bytes | None,
        *,
        page_widths: list[float] | None = None,
        notify_ready: bool = True,
        keep_display_width: bool = False,
    ) -> None:
        """
        Load PDF pages into the viewer.

        ``notify_ready``: call ``on_pages_ready`` once (first open / window size).
        ``keep_display_width``: reuse current fit width (Remove/Save preview — no resize flicker).
        """
        prev_w = self._display_width if keep_display_width else 0
        self.clear()
        if not data:
            self._canvas.create_text(12, 12, anchor="nw", fill="#888888", text=self._placeholder)
            return
        pages = render_pdf_pages(data, scale=2.0)
        if not pages:
            self._canvas.create_text(12, 12, anchor="nw", fill="#888888", text=_("Could not render PDF pages."))
            return
        self._page_pils = [p.convert("RGB") for p in pages]
        if page_widths and len(page_widths) == len(self._page_pils):
            self._page_widths_u = list(page_widths)
        else:
            # Assume PDF points ≈ rendered/2 when scale=2
            self._page_widths_u = [p.width / 2.0 for p in self._page_pils]
        self._display_width = prev_w if keep_display_width and prev_w >= 80 else 0
        self._refit_retries = 0
        # Prefer one owner for first paint (avoids size→refit→resize flicker).
        if notify_ready and self._on_pages_ready is not None:
            self.after_idle(self._on_pages_ready)
        else:
            self.after_idle(self._refit)

    def show_pil_pages(self, pages: Sequence[Image.Image], *, notify_ready: bool = True) -> None:
        self.clear()
        self._page_pils = [p.convert("RGB") for p in pages]
        self._page_widths_u = [float(p.width) for p in self._page_pils]
        self._display_width = 0
        self._refit_retries = 0
        if notify_ready and self._on_pages_ready is not None:
            self.after_idle(self._on_pages_ready)
        else:
            self.after_idle(self._refit)

    def set_overlays(
        self,
        hits: Sequence[ReportHit],
        *,
        excluded_keys: set[str] | None = None,
        exclude_rects: Sequence[UserRectangle] | None = None,
        blackout_rects: Sequence[UserRectangle] | None = None,
        pending: Sequence[UserRectangle] | None = None,
    ) -> None:
        self._hits = list(hits)
        self._excluded_keys = set(excluded_keys or ())
        self._exclude_rects = list(exclude_rects or ())
        self._blackout_rects = list(blackout_rects or ())
        self._pending = list(pending or ())
        self._redraw_overlays()

    def _on_configure(self, _event=None) -> None:
        if self._suspend_configure_refit:
            return
        # Scrollbar sits beside the canvas; use full canvas width for fit-width.
        w = max(self._canvas.winfo_width() - _PAGE_X, 100)
        if not self._page_pils:
            return
        if abs(w - self._display_width) < 4:
            return
        self._display_width = w
        self._refit()

    def _refit(self) -> None:
        if not self._page_pils:
            return
        raw_w = int(self._canvas.winfo_width())
        # Prefer an explicit target width (set while withdrawn) over waiting on winfo.
        planned = self._display_width if self._display_width >= 80 else 0
        if raw_w < 80 and planned < 80 and self._refit_retries < 20:
            self._refit_retries += 1
            self.after(16, self._refit)
            return
        self._refit_retries = 0
        # Fit-width: page spans the canvas (no letterbox / black band on the RHS).
        from_canvas = (raw_w - _PAGE_X) if raw_w >= 80 else 0
        avail_w = max(from_canvas, planned, 400)
        self._display_width = avail_w
        self._canvas.delete("all")
        for photo in self._photos:
            dispose_photo_image(self, photo)
        self._photos.clear()
        self._page_offsets.clear()
        self._page_heights.clear()
        y = 4
        for i, pil in enumerate(self._page_pils):
            ratio = avail_w / float(pil.width)
            w = avail_w
            nh = max(1, int(pil.height * ratio))
            resized = pil.resize((w, nh), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(resized)
            self._photos.append(photo)
            self._page_offsets.append(y)
            self._page_heights.append(nh)
            self._canvas.create_image(_PAGE_X, y, anchor="nw", image=photo, tags=("page", f"page{i}"))
            y += nh + 8
        page_w_u = self._page_widths_u[0] if self._page_widths_u else float(avail_w)
        self._scale = avail_w / max(page_w_u, 1.0)
        self._content_height = y
        self._canvas.configure(scrollregion=(0, 0, avail_w + _PAGE_X, y))
        self._redraw_overlays()

    def _page_at_canvas_y(self, cy: int) -> int | None:
        for i, (top, h) in enumerate(zip(self._page_offsets, self._page_heights, strict=True)):
            if top <= cy < top + h:
                return i
        return None

    def _user_to_canvas(self, page_index: int, x: float, y: float) -> tuple[int, int]:
        top = self._page_offsets[page_index] if page_index < len(self._page_offsets) else 0
        return int(_PAGE_X + x * self._scale), int(top + y * self._scale)

    def _canvas_to_user(self, cx: int, cy: int) -> tuple[int, float, float] | None:
        page = self._page_at_canvas_y(cy)
        if page is None:
            return None
        top = self._page_offsets[page]
        ux = (cx - _PAGE_X) / max(self._scale, 1e-6)
        uy = (cy - top) / max(self._scale, 1e-6)
        return page, ux, uy

    def _hit_canvas_box(self, hit: ReportHit) -> tuple[int, int, int, int] | None:
        if hit.page_index >= len(self._page_offsets):
            return None
        x0, y0, x1, y1 = hit.rect
        a = self._user_to_canvas(hit.page_index, x0, y0)
        b = self._user_to_canvas(hit.page_index, x1, y1)
        return min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])

    def _hit_at_canvas(self, cx: int, cy: int) -> ReportHit | None:
        """Geometric hit-test (hollow outline rects are not pickable via find_overlapping)."""
        pad = 3
        for hit in reversed(self._hits):
            box = self._hit_canvas_box(hit)
            if box is None:
                continue
            x0, y0, x1, y1 = box
            if (x0 - pad) <= cx <= (x1 + pad) and (y0 - pad) <= cy <= (y1 + pad):
                return hit
        return None

    def _redraw_overlays(self) -> None:
        self._canvas.delete("overlay")
        for hit in self._hits:
            box = self._hit_canvas_box(hit)
            if box is None:
                continue
            x0, y0, x1, y1 = box
            # Series View style: coloured outline only (no solid fill over the page).
            color = "#888888" if hit.key in self._excluded_keys else entity_color_hex(hit.label)
            self._canvas.create_rectangle(
                x0,
                y0,
                x1,
                y1,
                outline=color,
                fill="",
                width=2,
                tags=("overlay", "hit", hit.key),
            )
        for rect in self._exclude_rects:
            self._draw_user_rect(rect, outline="white", dash=_EXCLUDE_DASH, tags=("overlay", "exclude"))
        for rect in self._blackout_rects:
            self._draw_user_rect(rect, outline=_BLACKOUT_OUTLINE, tags=("overlay", "blackout"))
        for rect in self._pending:
            self._draw_user_rect(rect, outline=_PENDING_OUTLINE, tags=("overlay", "pending"))

    def _draw_user_rect(self, rect: UserRectangle, *, outline: str, tags: tuple, dash=()) -> None:
        # User rects stored in page-0 top-left user units for single-page reports.
        x0, y0, x1, y1 = rect.get_bounding_box()
        page = 0
        a = self._user_to_canvas(page, float(x0), float(y0))
        b = self._user_to_canvas(page, float(x1), float(y1))
        kw = {"outline": outline, "width": 2, "tags": tags}
        if dash:
            kw["dash"] = dash
        self._canvas.create_rectangle(a[0], a[1], b[0], b[1], **kw)

    def _hover_text(self, event: tk.Event) -> str | None:
        cx = int(self._canvas.canvasx(event.x))
        cy = int(self._canvas.canvasy(event.y))
        hit = self._hit_at_canvas(cx, cy)
        if hit is None:
            return None
        return f"{entity_label_display(hit.label)} — {hit.text}"

    def _on_press(self, event: tk.Event) -> None:
        cx = int(self._canvas.canvasx(event.x))
        cy = int(self._canvas.canvasy(event.y))
        # Click exclude outline to delete
        if self._on_delete_exclude is not None:
            mapped = self._canvas_to_user(cx, cy)
            if mapped is not None:
                _page, ux, uy = mapped
                if self._on_delete_exclude(int(ux), int(uy)):
                    return
        # Click hit to toggle exclude-from-Remove
        hit = self._hit_at_canvas(cx, cy)
        if hit is not None and self._on_toggle_hit is not None:
            self._on_toggle_hit(hit.key)
            return
        self._draw_start = (cx, cy)
        self._draw_rect_id = None

    def _on_drag(self, event: tk.Event) -> None:
        if self._draw_start is None:
            return
        cx = int(self._canvas.canvasx(event.x))
        cy = int(self._canvas.canvasy(event.y))
        x0, y0 = self._draw_start
        if self._draw_rect_id is not None:
            self._canvas.delete(self._draw_rect_id)
        self._draw_rect_id = self._canvas.create_rectangle(
            x0, y0, cx, cy, outline=_PENDING_OUTLINE, width=2, tags=("overlay", "drag")
        )

    def _on_release(self, event: tk.Event) -> None:
        if self._draw_start is None:
            return
        cx = int(self._canvas.canvasx(event.x))
        cy = int(self._canvas.canvasy(event.y))
        x0, y0 = self._draw_start
        self._draw_start = None
        if self._draw_rect_id is not None:
            self._canvas.delete(self._draw_rect_id)
            self._draw_rect_id = None
        if abs(cx - x0) < 4 or abs(cy - y0) < 4:
            return
        a = self._canvas_to_user(x0, y0)
        b = self._canvas_to_user(cx, cy)
        if a is None or b is None:
            return
        _pa, ux0, uy0 = a
        _pb, ux1, uy1 = b
        rect = UserRectangle(
            top_left=(int(min(ux0, ux1)), int(min(uy0, uy1))),
            bottom_right=(int(max(ux0, ux1)), int(max(uy0, uy1))),
        )
        self._pending.append(rect)
        if self._on_pending_rects is not None:
            self._on_pending_rects()
        self._redraw_overlays()

    def take_pending(self) -> list[UserRectangle]:
        out = list(self._pending)
        self._pending.clear()
        self._redraw_overlays()
        return out

    def destroy(self) -> None:
        self.clear()
        super().destroy()
