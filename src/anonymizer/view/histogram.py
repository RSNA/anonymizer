import logging
import tkinter as tk
from typing import Callable

import customtkinter as ctk
import numpy as np

logger = logging.getLogger(__name__)


class Histogram(ctk.CTkFrame):
    """
    A CustomTkinter widget to display an image histogram and allow
    interactive adjustment of Window Level (WL) and Window Width (WW)
    indicated by superimposed lines. Includes min/max intensity labels.
    """

    DEFAULT_NUM_BINS = 256

    def __init__(
        self,
        master,
        num_bins=DEFAULT_NUM_BINS,
        update_callback: Callable[[float, float], None] | None = None,  # Function to call with (wl, ww) when updated
    ):
        super().__init__(master)
        self.master = master
        self.num_bins = num_bins
        self.update_callback = update_callback

        self.HISTOGRAM_BACKGROUND_COLOR = ctk.ThemeManager.theme["Histogram"]["fg_color"]
        self.HISTOGRAM_BAR_COLOR = ctk.ThemeManager.theme["Histogram"]["bar_color"]
        self.AXIS_LABEL_COLOR = ctk.ThemeManager.theme["Histogram"]["axis_label_color"]
        self.WL_LINE_COLOR = ctk.ThemeManager.theme["Histogram"]["wl_line_color"]
        self.WW_BOUNDARY_LINE_COLOR = ctk.ThemeManager.theme["Histogram"]["ww_boundary_line_color"]

        # --- Internal State ---
        self.hist_data = np.array([])
        self.bin_edges = np.array([])
        self.image_min_intensity = 0.0
        self.image_max_intensity = 255.0  # Default assumption
        self.max_hist_count = 1  # Avoid division by zero

        # Using tkinter DoubleVar for easy tracing if needed elsewhere,
        # but mainly used as simple float storage here.
        self._current_wl = tk.DoubleVar(value=128.0)
        self._current_ww = tk.DoubleVar(value=256.0)

        # Interaction state
        self._is_left_dragging = False
        self._is_right_dragging = False
        self._drag_start_x = 0
        self._drag_start_wl = 0.0
        self._drag_start_ww = 1.0

        # --- Widget Layout ---
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)  # Canvas row
        self.grid_rowconfigure(1, weight=0)  # Label row

        self.canvas = tk.Canvas(
            self,
            bg=self._apply_appearance_mode(self.HISTOGRAM_BACKGROUND_COLOR),
            borderwidth=0,
            highlightthickness=0,
        )
        self.canvas.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="nsew")

        self.label_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.label_frame.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="ew")
        self.label_frame.grid_columnconfigure((0, 1), weight=1)

        self.wl_label = ctk.CTkLabel(self.label_frame, text="WL: ---", anchor="w")
        self.wl_label.grid(row=0, column=0, sticky="w")

        self.ww_label = ctk.CTkLabel(self.label_frame, text="WW: ---", anchor="e")
        self.ww_label.grid(row=0, column=1, sticky="e")

        # --- Bind Mouse Events ---
        self.canvas.bind("<ButtonPress-1>", self._on_left_press)
        self.canvas.bind("<B1-Motion>", self._on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_left_release)
        self.canvas.bind("<ButtonPress-3>", self._on_right_press)
        self.canvas.bind("<B3-Motion>", self._on_right_drag)
        self.canvas.bind("<ButtonRelease-3>", self._on_right_release)
        self.bind("<Configure>", self._on_configure)

    # --- Public Methods ---
    def update_image(self, image_frame: np.ndarray):
        """
        Updates histogram data based on a new image frame (expects grayscale)
        and triggers a redraw. Does NOT modify WL/WW internally.
        """
        logger.debug(f"Updating histogram with new image data. image shape: {image_frame.shape}")
        self._calculate_histogram(image_frame)
        # Redraw using the current internal WL/WW (which should be set externally via set_wlww)
        self._redraw()
        self._update_labels()

    def set_wlww(self, wl: float, ww: float, redraw: bool = True):
        logger.debug(f"Setting WL: {wl}, WW: {ww}")
        wl_changed = abs(wl - self._current_wl.get()) > 0.01
        ww_changed = abs(ww - self._current_ww.get()) > 0.01
        ww_clamped = max(1.0, ww)

        if wl_changed or ww_changed:
            self._current_wl.set(wl)
            self._current_ww.set(ww_clamped)
            if redraw:
                self._redraw()
                self._update_labels()

    def get_wlww(self) -> tuple[float, float]:
        return self._current_wl.get(), self._current_ww.get()

    # --- Internal Calculation and Drawing Methods ---
    def _calculate_histogram(self, image_frame: np.ndarray):
        logger.debug("Calculating histogram data.")
        self.image_min_intensity = float(np.nanmin(image_frame))
        self.image_max_intensity = float(np.nanmax(image_frame))
        if self.image_min_intensity >= self.image_max_intensity:
            self.image_max_intensity = self.image_min_intensity + 1
        self.hist_data, self.bin_edges = np.histogram(
            image_frame.flatten(), bins=self.num_bins, range=(self.image_min_intensity, self.image_max_intensity)
        )
        self.max_hist_count = float(np.max(self.hist_data))
        if self.max_hist_count == 0:
            self.max_hist_count = 1.0

    def _redraw(self):
        """Clears and redraws the entire histogram canvas content."""
        logger.debug("Redrawing histogram canvas.")
        if self.canvas.winfo_width() <= 1:
            logger.error("Histogram canvas width is 0. Cannot redraw.")
            return
        self.canvas.delete("all")
        self._draw_histogram_bars()
        self._draw_wlww_indicators()
        self._draw_axis_labels()

    def _draw_histogram_bars(self):
        """Draws the histogram bars on the main canvas."""
        logger.debug("Drawing histogram bars.")
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        if canvas_width <= 1 or canvas_height <= 1 or len(self.hist_data) == 0:
            return
        bar_color = self._apply_appearance_mode(self.HISTOGRAM_BAR_COLOR)
        bar_area_height = canvas_height - 15
        if bar_area_height <= 0:
            bar_area_height = canvas_height
        for i in range(self.num_bins):
            x0 = self._intensity_to_x(self.bin_edges[i], canvas_width)
            x1 = self._intensity_to_x(self.bin_edges[i + 1], canvas_width)
            bar_height_normalized = (self.hist_data[i] / self.max_hist_count) * (bar_area_height * 0.98)
            y0 = bar_area_height - bar_height_normalized
            y1 = bar_area_height
            if x1 <= x0:
                x1 = x0 + 1
            self.canvas.create_rectangle(x0, y0, x1, y1, fill=bar_color, outline="", tags="histogram_bar")

    def _draw_wlww_indicators(self):
        """Draws the WL line and WW boundary lines superimposed on the histogram canvas."""
        logger.debug("Drawing WL/WW indicators.")
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        if canvas_width <= 1 or canvas_height <= 1:
            return
        indicator_height = canvas_height - 15
        if indicator_height <= 0:
            indicator_height = canvas_height

        wl = self._current_wl.get()
        ww = self._current_ww.get()
        ww_min = wl - ww / 2.0
        ww_max = wl + ww / 2.0
        ww_min_x = self._intensity_to_x(ww_min, canvas_width)
        ww_max_x = self._intensity_to_x(ww_max, canvas_width)
        wl_x = self._intensity_to_x(wl, canvas_width)

        self.canvas.create_line(
            ww_min_x,
            0,
            ww_min_x,
            indicator_height,
            fill=self._apply_appearance_mode(self.WW_BOUNDARY_LINE_COLOR),
            width=1,
            dash=(4, 4),
            tags="ww_line",
        )
        self.canvas.create_line(
            ww_max_x,
            0,
            ww_max_x,
            indicator_height,
            fill=self._apply_appearance_mode(self.WW_BOUNDARY_LINE_COLOR),
            width=1,
            dash=(4, 4),
            tags="ww_line",
        )
        self.canvas.create_line(
            wl_x,
            0,
            wl_x,
            indicator_height,
            fill=self._apply_appearance_mode(self.WL_LINE_COLOR),
            width=2,
            tags="wl_line",
        )

    def _draw_axis_labels(self):
        """Draws the min and max intensity labels on the x-axis."""
        logger.debug("Drawing axis labels.")
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        if canvas_width <= 1 or canvas_height <= 1:
            return
        label_y = canvas_height - 5
        label_color = self._apply_appearance_mode(self.AXIS_LABEL_COLOR)
        label_font = ctk.CTkFont(size=10)
        min_text = f"{self.image_min_intensity:.0f}"
        self.canvas.create_text(
            5, label_y, text=min_text, anchor="sw", fill=label_color, font=label_font, tags="axis_label"
        )
        max_text = f"{self.image_max_intensity:.0f}"
        self.canvas.create_text(
            canvas_width - 5, label_y, text=max_text, anchor="se", fill=label_color, font=label_font, tags="axis_label"
        )

    def _update_labels(self):
        """Updates the WL and WW text labels inside the histogram widget."""
        if hasattr(self, "wl_label") and self.wl_label.winfo_exists():
            wl = self._current_wl.get()
            self.wl_label.configure(text=f"WL: {wl:.1f}")
        if hasattr(self, "ww_label") and self.ww_label.winfo_exists():
            ww = self._current_ww.get()
            self.ww_label.configure(text=f"WW: {ww:.1f}")

    # --- Coordinate Mapping ---
    def _intensity_to_x(self, intensity: float, canvas_width: int) -> float:
        if canvas_width <= 1:
            return 0.0
        intensity_range = self.image_max_intensity - self.image_min_intensity
        if intensity_range <= 0:
            return 0.0
        clamped_intensity = max(self.image_min_intensity, min(self.image_max_intensity, intensity))
        normalized_intensity = (clamped_intensity - self.image_min_intensity) / intensity_range
        x = normalized_intensity * canvas_width
        return max(0.0, min(float(canvas_width), x))

    def _x_to_intensity(self, x_coordinate: float, canvas_width: int) -> float:
        if canvas_width <= 0:
            return self.image_min_intensity
        clamped_x = max(0.0, min(float(canvas_width), x_coordinate))
        normalized_x = clamped_x / canvas_width
        intensity_range = self.image_max_intensity - self.image_min_intensity
        if intensity_range <= 0:
            return self.image_min_intensity
        intensity = self.image_min_intensity + normalized_x * intensity_range
        return max(self.image_min_intensity, min(self.image_max_intensity, intensity))

    # --- Event Handlers ---
    def _on_configure(self, event=None):
        self.after_idle(self._redraw)

    def _on_left_press(self, event):
        self._is_left_dragging = True
        self._drag_start_x = event.x
        self._drag_start_wl = self._current_wl.get()
        new_wl = self._x_to_intensity(event.x, self.canvas.winfo_width())
        self._current_wl.set(new_wl)
        self._redraw()
        self._update_labels()
        if self.update_callback:
            self.update_callback(self._current_wl.get(), self._current_ww.get())

    def _on_left_drag(self, event):
        if not self._is_left_dragging:
            return
        new_wl = self._x_to_intensity(event.x, self.canvas.winfo_width())
        if abs(new_wl - self._current_wl.get()) > 0.01:
            self._current_wl.set(new_wl)
            self._redraw()
            self._update_labels()
            if self.update_callback:
                self.update_callback(self._current_wl.get(), self._current_ww.get())

    def _on_left_release(self, event):
        self._is_left_dragging = False

    def _on_right_press(self, event):
        self._is_right_dragging = True
        self._drag_start_x = event.x
        self._drag_start_ww = self._current_ww.get()

    def _on_right_drag(self, event):
        if not self._is_right_dragging:
            return
        canvas_width = self.canvas.winfo_width()
        if canvas_width <= 0:
            return
        delta_x = event.x - self._drag_start_x
        intensity_range = self.image_max_intensity - self.image_min_intensity
        if intensity_range <= 0:
            return
        sensitivity_factor = 1.5
        delta_ww = (delta_x / canvas_width) * intensity_range * sensitivity_factor
        new_ww = self._drag_start_ww + delta_ww
        new_ww = max(1.0, new_ww)
        if abs(new_ww - self._current_ww.get()) > 0.01:
            self._current_ww.set(new_ww)
            self._redraw()
            self._update_labels()
            if self.update_callback:
                self.update_callback(self._current_wl.get(), self._current_ww.get())

    def _on_right_release(self, event):
        self._is_right_dragging = False
