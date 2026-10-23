"""Fit-width PDF page viewer (graphic preview only; PHI highlights live in the text panel)."""

import tkinter as tk
from collections.abc import Callable, Sequence
from tkinter import Misc

import customtkinter as ctk
from PIL import Image, ImageTk

from anonymizer.controller.ai.embedded_phi.report.process_report_text import render_pdf_pages
from anonymizer.utils.translate import _
from anonymizer.view.common.ctk_safe import dispose_photo_image

# Canvas inset left of the page image (matches create_image x=4).
_PAGE_X = 4


class PdfPageView(ctk.CTkFrame):
    """Scrollable fit-width page viewer for Encapsulated PDF preview."""

    def __init__(
        self,
        master: Misc,
        *,
        on_pages_ready: Callable[[], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self._on_pages_ready = on_pages_ready
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._canvas = tk.Canvas(self, highlightthickness=0, bg="#ffffff")
        self._vscroll = ctk.CTkScrollbar(self, orientation="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._vscroll.set)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._vscroll.grid(row=0, column=1, sticky="ns")

        self._photos: list[ImageTk.PhotoImage] = []
        self._page_pils: list[Image.Image] = []
        self._page_offsets: list[int] = []
        self._page_heights: list[int] = []
        self._display_width = 0
        self._content_height = 0
        self._placeholder = _("No PDF pages to display.")
        self._refit_retries = 0
        self._suspend_configure_refit = False

        self._canvas.bind("<Configure>", self._on_configure)
        self._bind_mousewheel()

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

    def show_pdf_bytes(
        self,
        data: bytes | None,
        *,
        notify_ready: bool = True,
        keep_display_width: bool = False,
    ) -> None:
        """
        Load PDF pages into the viewer.

        Args:
            data: Raw PDF bytes, or None for placeholder.
            notify_ready: Call on_pages_ready once after load.
            keep_display_width: Reuse current fit width (Save preview).
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
        self._display_width = prev_w if keep_display_width and prev_w >= 80 else 0
        self._refit_retries = 0
        if notify_ready and self._on_pages_ready is not None:
            self.after_idle(self._on_pages_ready)
        else:
            self.after_idle(self._refit)

    def show_pil_pages(self, pages: Sequence[Image.Image], *, notify_ready: bool = True) -> None:
        """
        Show pre-rasterized pages.

        Args:
            pages: PIL images, one per page.
            notify_ready: Call on_pages_ready once after load.
        """
        self.clear()
        self._page_pils = [p.convert("RGB") for p in pages]
        self._display_width = 0
        self._refit_retries = 0
        if notify_ready and self._on_pages_ready is not None:
            self.after_idle(self._on_pages_ready)
        else:
            self.after_idle(self._refit)

    def _on_configure(self, _event=None) -> None:
        if self._suspend_configure_refit:
            return
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
        planned = self._display_width if self._display_width >= 80 else 0
        if raw_w < 80 and planned < 80 and self._refit_retries < 20:
            self._refit_retries += 1
            self.after(16, self._refit)
            return
        self._refit_retries = 0
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
        self._content_height = y
        self._canvas.configure(scrollregion=(0, 0, avail_w + _PAGE_X, y))

    def destroy(self) -> None:
        self.clear()
        super().destroy()
