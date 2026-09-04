import logging
import tkinter as tk
from typing import Callable

import customtkinter as ctk
import cv2  # For potential BGR -> Gray conversion
import numpy as np

# --- Configuration ---
DEFAULT_NUM_BINS = 256
HISTOGRAM_BAR_COLOR = ("gray70", "gray30")
WL_LINE_COLOR = "red"
WW_BOUNDARY_LINE_COLOR = "cyan"
AXIS_LABEL_COLOR = ("gray10", "gray90")
HISTOGRAM_BG_COLOR = ("gray85", "gray15")  # Example background colors
Y_AXIS_PERCENTILE = 99.5  # Clip histogram display Y-axis

logger = logging.getLogger(__name__)


class Histogram(ctk.CTkFrame):
    """
    Displays an image histogram calculated from data provided at init.
    Indicates current Window Level (WL) and Window Width (WW) via lines.
    Allows interactive WL/WW adjustment via mouse drags on the histogram itself,
    notifying the parent via a callback.
    """

    def __init__(
        self,
        master,
        image_frame: np.ndarray | None,  # Image data (mean projection likely)
        initial_wl: float,
        initial_ww: float,
        width: int = 200,
        height: int = 100,
        num_bins: int = DEFAULT_NUM_BINS,
        update_callback: Callable[[float, float], None] | None = None,  # Func(wl, ww)
    ):
        super().__init__(master)

        self.num_bins = num_bins
        self.update_callback = update_callback

        # --- Internal State ---
        self._hist_counts: np.ndarray | None = None
        self._bin_edges: np.ndarray | None = None
        self._image_min_intensity: float = 0.0
        self._image_max_intensity: float = 255.0
        self._y_max_display: float = 1.0

        # Store WL/WW state directly as floats
        self._current_wl: float = initial_wl
        self._current_ww: float = max(1.0, initial_ww)  # Ensure WW >= 1

        # Interaction state
        self._is_left_dragging = False
        self._is_right_dragging = False
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._drag_start_wl = 0.0
        self._drag_start_ww = 1.0
        self._resize_debounce_id: str | None = None

        # --- Widget Layout ---
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)  # Canvas row expands
        self.grid_rowconfigure(0, weight=0)  # Label row fixed

        self.label_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.label_frame.grid(row=0, column=0, padx=5, pady=(5, 0), sticky="ew")
        self.label_frame.grid_columnconfigure((0, 1), weight=1)

        self.wl_label = ctk.CTkLabel(self.label_frame, text="WL: ---", anchor="w")
        self.wl_label.grid(row=0, column=0, sticky="w")

        self.ww_label = ctk.CTkLabel(self.label_frame, text="WW: ---", anchor="e")
        self.ww_label.grid(row=0, column=1, sticky="e")

        self.hist_canvas = tk.Canvas(
            self,
            background=self._apply_appearance_mode(HISTOGRAM_BG_COLOR),
            borderwidth=0,
            highlightthickness=0,
            width=width,  # Set initial requested size
            height=height - 30,  # Adjust height for labels
        )
        self.hist_canvas.grid(row=1, column=0, padx=5, pady=(0, 5), sticky="nsew")

        # --- Bind Mouse Events to Canvas ---
        self.hist_canvas.bind("<ButtonPress-1>", self._on_left_press)
        self.hist_canvas.bind("<B1-Motion>", self._on_left_drag)
        self.hist_canvas.bind("<ButtonRelease-1>", self._on_left_release)
        self.hist_canvas.bind("<ButtonPress-3>", self._on_right_press)
        self.hist_canvas.bind("<B3-Motion>", self._on_right_drag)
        self.hist_canvas.bind("<ButtonRelease-3>", self._on_right_release)
        self.hist_canvas.bind("<Configure>", self._on_configure)  # Draw on resize/initial configure

        # --- Calculate Histogram and Update Labels Immediately ---
        self._calculate_histogram(image_frame)
        self._update_labels()
        # Initial draw will be triggered by the first <Configure> event

    # --- Public Method ---
    def set_wlww(self, wl: float, ww: float):
        """Programmatically sets the Window Level/Width and updates indicator."""
        ww_clamped = max(1.0, ww)
        wl_changed = abs(wl - self._current_wl) > 0.01
        ww_changed = abs(ww_clamped - self._current_ww) > 0.01

        if wl_changed or ww_changed:
            logger.debug(f"Histogram externally set WL/WW: {wl:.1f}/{ww_clamped:.1f}")
            self._current_wl = wl
            self._current_ww = ww_clamped
            self._update_labels()  # Update labels immediately
            # Redraw histogram canvas only if widget exists and has size
            if hasattr(self, "hist_canvas") and self.hist_canvas.winfo_exists() and self.hist_canvas.winfo_width() > 1:
                self._redraw()  # Redraw histogram with new indicators

    def get_wlww(self) -> tuple[float, float]:
        """Gets the current internal Window Level and Window Width."""
        return self._current_wl, self._current_ww

    # --- Internal Calculation and Drawing Methods ---
    def _calculate_histogram(self, image_frame: np.ndarray | None):
        """Calculates histogram data, intensity range, and Y-axis display max."""
        if image_frame is None or image_frame.size == 0:
            logger.warning("Histogram received no image data for calculation.")
            self._hist_counts = None
            self._bin_edges = None
            self._image_min_intensity = 0.0
            self._image_max_intensity = 255.0
            self._y_max_display = 1.0
            return

        try:
            image_gray = image_frame  # Assume input is already grayscale
            if image_frame.ndim == 3:
                if image_frame.shape[-1] == 3:
                    image_gray = cv2.cvtColor(image_frame, cv2.COLOR_BGR2GRAY)
                elif image_frame.shape[-1] == 1:
                    image_gray = image_frame.squeeze(axis=-1)
                else:
                    raise ValueError(f"Unsupported channel count: {image_frame.shape[-1]}")
            elif image_frame.ndim != 2:
                raise ValueError(f"Unsupported dimensions: {image_frame.ndim}")

            self._image_min_intensity = float(np.min(image_gray))
            self._image_max_intensity = float(np.max(image_gray))
            hist_range = (self._image_min_intensity, self._image_max_intensity)

            if hist_range[0] >= hist_range[1]:
                logger.warning(
                    f"Histogram range invalid [{hist_range[0]}, {hist_range[1]}] (Uniform Image?). Creating dummy."
                )
                # Handle uniform image: Create flat histogram or single peak
                self._counts = np.zeros(self.num_bins)
                bin_index = (
                    np.clip(int((hist_range[0] - hist_range[0]) / 1.0 * self.num_bins), 0, self.num_bins - 1)
                    if hist_range[0] == hist_range[1]
                    else 0
                )
                self._counts[bin_index] = image_gray.size  # Put all counts in one bin
                self._bin_edges = np.linspace(
                    hist_range[0], hist_range[1] + 1, self.num_bins + 1
                )  # Need range slightly > 0
                self._y_max_display = max(1.0, float(image_gray.size))  # Y max is total pixels
            else:
                self._counts, self._bin_edges = np.histogram(image_gray, bins=self.num_bins, range=hist_range)

            # Calculate Y max for display using percentile clipping
            if self._counts is not None and self._counts.size > 0 and np.max(self._counts) > 0:
                counts_for_scaling = self._counts[self._counts > 0]
                if counts_for_scaling.size > 0:
                    y_max = np.percentile(counts_for_scaling, Y_AXIS_PERCENTILE) if counts_for_scaling.size > 0 else 1.0
                self._y_max_display = float(max(1.0, y_max))
            else:
                self._y_max_display = 1.0

            logger.debug(
                f"Histogram calculated. Range=[{self._image_min_intensity:.1f}, {self._image_max_intensity:.1f}], Display Y-Max={self._y_max_display:.1f}"
            )

        except Exception as e:
            logger.exception(f"Error calculating histogram: {e}")
            self._counts = None
            self._bin_edges = None
            self._y_max_display = 1.0

    def _redraw(self):
        """Clears and redraws the entire canvas content."""
        if not hasattr(self, "hist_canvas") or not self.hist_canvas.winfo_exists():
            return
        canvas_width = self.hist_canvas.winfo_width()
        canvas_height = self.hist_canvas.winfo_height()
        if canvas_width <= 1 or canvas_height <= 1:
            return  # Canvas not ready

        hist_bg_color = self._apply_appearance_mode(HISTOGRAM_BG_COLOR)
        self.hist_canvas.configure(background=hist_bg_color)
        self.hist_canvas.delete("all")

        if self._counts is not None and self._bin_edges is not None:
            self._draw_histogram_bars(canvas_width, canvas_height)
            self._draw_wlww_indicators(canvas_width, canvas_height)
            self._draw_axis_labels(canvas_width, canvas_height)
        else:
            label_color = self._apply_appearance_mode(AXIS_LABEL_COLOR)
            label_font = ctk.CTkFont(size=12)
            self.hist_canvas.create_text(
                canvas_width / 2, canvas_height / 2, text="No Histogram Data", fill=label_color, font=label_font
            )

    def _draw_histogram_bars(self, canvas_width: int, canvas_height: int):
        """Draws the histogram bars."""
        if self._counts is None or self._bin_edges is None or self._y_max_display is None or self._y_max_display <= 0:
            return

        bar_color = self._apply_appearance_mode(HISTOGRAM_BAR_COLOR)
        bar_area_height = canvas_height - 15
        if bar_area_height <= 0:
            bar_area_height = 1

        bin_min = self._bin_edges[0]
        bin_max = self._bin_edges[-1]
        bin_range = bin_max - bin_min
        if bin_range <= 0:
            bin_range = 1  # Avoid division by zero

        y_scale = bar_area_height / self._y_max_display

        for i, count in enumerate(self._counts):
            x0 = ((self._bin_edges[i] - bin_min) / bin_range) * canvas_width
            x1 = ((self._bin_edges[i + 1] - bin_min) / bin_range) * canvas_width
            bar_height = min(count, self._y_max_display) * y_scale  # Clip height
            y0 = bar_area_height - bar_height
            y1 = bar_area_height
            # Ensure min 1 pixel width and positive height
            if x1 <= x0:
                x1 = x0 + 1
            if bar_height >= 1:
                self.hist_canvas.create_rectangle(x0, y0, x1, y1, fill=bar_color, outline="", tags="histogram_bar")

    def _draw_wlww_indicators(self, canvas_width: int, canvas_height: int):
        """Draws the WL line and WW boundary lines."""
        if self._current_wl is None or self._current_ww is None or self._bin_edges is None:
            return
        indicator_height = max(1, canvas_height - 15)  # Ensure positive height

        wl = self._current_wl
        ww = self._current_ww
        ww_min = wl - ww / 2.0
        ww_max = wl + ww / 2.0
        ww_min_x = self._intensity_to_x(ww_min, canvas_width)
        ww_max_x = self._intensity_to_x(ww_max, canvas_width)
        wl_x = self._intensity_to_x(wl, canvas_width)

        self.hist_canvas.create_line(
            ww_min_x, 0, ww_min_x, indicator_height, fill=WW_BOUNDARY_LINE_COLOR, width=1, dash=(4, 4), tags="ww_line"
        )
        self.hist_canvas.create_line(
            ww_max_x, 0, ww_max_x, indicator_height, fill=WW_BOUNDARY_LINE_COLOR, width=1, dash=(4, 4), tags="ww_line"
        )
        self.hist_canvas.create_line(wl_x, 0, wl_x, indicator_height, fill=WL_LINE_COLOR, width=2, tags="wl_line")

    def _draw_axis_labels(self, canvas_width: int, canvas_height: int):
        """Draws the min and max intensity labels on the x-axis."""
        label_y = canvas_height - 5
        label_color = self._apply_appearance_mode(AXIS_LABEL_COLOR)
        label_font = ctk.CTkFont(size=10)
        precision = 0 if (self._image_max_intensity - self._image_min_intensity) > 10 else 1
        min_text = f"{self._image_min_intensity:.{precision}f}"
        max_text = f"{self._image_max_intensity:.{precision}f}"
        self.hist_canvas.create_text(
            5, label_y, text=min_text, anchor="sw", fill=label_color, font=label_font, tags="axis_label"
        )
        self.hist_canvas.create_text(
            canvas_width - 5, label_y, text=max_text, anchor="se", fill=label_color, font=label_font, tags="axis_label"
        )

    def _update_labels(self):
        """Updates the WL and WW text labels inside this widget."""
        if hasattr(self, "wl_label") and self.wl_label.winfo_exists():
            self.wl_label.configure(text=f"WL: {self._current_wl:.1f}")
        if hasattr(self, "ww_label") and self.ww_label.winfo_exists():
            self.ww_label.configure(text=f"WW: {self._current_ww:.1f}")

    # --- Coordinate Mapping ---
    def _intensity_to_x(self, intensity: float, canvas_width: int) -> float:
        if canvas_width <= 1:
            return 0.0
        intensity_range = self._image_max_intensity - self._image_min_intensity
        if intensity_range <= 0:
            return 0.0  # Map to left if range is zero
        normalized_intensity = (intensity - self._image_min_intensity) / intensity_range
        x = normalized_intensity * canvas_width
        # Allow lines to be drawn slightly outside canvas for clarity if needed
        # return max(0.0, min(float(canvas_width), x))
        return float(x)

    def _x_to_intensity(self, x_coordinate: float, canvas_width: int) -> float:
        if canvas_width <= 0:
            return self._image_min_intensity
        # Don't clamp x_coordinate input here, allow mapping outside canvas bounds
        # clamped_x = max(0.0, min(float(canvas_width), x_coordinate))
        normalized_x = x_coordinate / canvas_width
        intensity_range = self._image_max_intensity - self._image_min_intensity
        if intensity_range <= 0:
            return self._image_min_intensity
        intensity = self._image_min_intensity + normalized_x * intensity_range
        return intensity  # Return potentially outside original min/max range

    # --- Event Handlers ---
    def _on_configure(self, event=None):
        if hasattr(self, "_resize_debounce_id") and self._resize_debounce_id:
            self.after_cancel(self._resize_debounce_id)
        self._resize_debounce_id = self.after(50, self._redraw)  # Debounce slightly

    def _on_left_press(self, event):
        """Start WL adjustment (Left Drag Up/Down)."""
        self._is_left_dragging = True
        self._drag_start_x = event.x
        self._drag_start_y = event.y
        self._drag_start_wl = self._current_wl

    def _on_left_drag(self, event):
        """Adjust WL during drag (Up/Down)."""
        if not self._is_left_dragging:
            return
        canvas_height = self.hist_canvas.winfo_height()
        if canvas_height <= 0:
            return

        delta_y = event.y - self._drag_start_y
        intensity_range = self._image_max_intensity - self._image_min_intensity
        if intensity_range <= 0:
            return

        # Sensitivity - adjust factor as needed
        wl_sensitivity_factor = 2.0  # Larger = slower change
        delta_wl = (-delta_y / canvas_height) * intensity_range * wl_sensitivity_factor
        new_wl = self._drag_start_wl + delta_wl

        if abs(new_wl - self._current_wl) > 0.01:
            self.set_wlww(new_wl, self._current_ww)  # Use setter
            if self.update_callback:
                self.update_callback(self._current_wl, self._current_ww)

    def _on_left_release(self, event):
        self._is_left_dragging = False

    def _on_right_press(self, event):
        """Start WW adjustment (Right Drag Left/Right)."""
        self._is_right_dragging = True
        self._drag_start_x = event.x
        self._drag_start_y = event.y
        self._drag_start_ww = self._current_ww

    def _on_right_drag(self, event):
        """Adjust WW during drag (Left/Right)."""
        if not self._is_right_dragging:
            return
        canvas_width = self.hist_canvas.winfo_width()
        if canvas_width <= 0:
            return

        delta_x = event.x - self._drag_start_x
        intensity_range = self._image_max_intensity - self._image_min_intensity
        if intensity_range <= 0:
            return

        ww_sensitivity_factor = 2.0  # Larger = slower change
        delta_ww = (delta_x / canvas_width) * intensity_range * ww_sensitivity_factor
        new_ww = self._drag_start_ww + delta_ww
        new_ww_clamped = max(1.0, new_ww)

        if abs(new_ww_clamped - self._current_ww) > 0.01:
            self.set_wlww(self._current_wl, new_ww_clamped)  # Use setter
            if self.update_callback:
                self.update_callback(self._current_wl, self._current_ww)

    def _on_right_release(self, event):
        self._is_right_dragging = False


from PIL import Image, ImageTk


# --- Simple Image Viewer Application ---
class SimpleImageViewer(ctk.CTk):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title("Simple Image Viewer with Histogram")
        self.geometry("900x650")
        self.original_image: np.ndarray | None = None
        self.grayscale_image: np.ndarray | None = None
        self.current_wl: float = 128.0
        self.current_ww: float = 256.0
        self.display_size: tuple[int, int] = (600, 600)  # Initial desired display size

        # Layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(0, weight=1)

        # Use tk.Canvas for image display
        self.image_canvas = tk.Canvas(self, bg="black", borderwidth=0, highlightthickness=0)
        self.image_canvas.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.canvas_image_item: int | None = None
        self.photo_image: ImageTk.PhotoImage | None = None

        # Controls Frame
        self.controls_frame = ctk.CTkFrame(self)
        self.controls_frame.grid(row=0, column=1, padx=10, pady=10, sticky="ns")

        self.histogram_widget: Histogram | None = None  # Placeholder

        # Load Buttons
        self.load_grayscale_button = ctk.CTkButton(
            self.controls_frame, text="Load 16-bit Grayscale", command=self.load_grayscale_sample
        )
        self.load_grayscale_button.pack(pady=5, padx=10, fill="x")
        self.load_rgb_button = ctk.CTkButton(self.controls_frame, text="Load RGB Sample", command=self.load_rgb_sample)
        self.load_rgb_button.pack(pady=5, padx=10, fill="x")

        # Load initial image
        self.load_grayscale_sample()

        # Bind resize event for main window
        self.bind("<Configure>", self.on_resize)

    def load_image(self, image_data: np.ndarray):
        """Loads new image, calculates initial WL/WW, creates histogram."""
        self.original_image = image_data
        initial_wl, initial_ww = 128.0, 256.0  # Defaults

        if image_data.ndim == 3 and image_data.shape[2] == 3:
            self.grayscale_image = cv2.cvtColor(image_data, cv2.COLOR_BGR2GRAY)
            initial_wl = 128.0
            initial_ww = 255.0
            logger.info(
                f"Loaded RGB, Grayscale range: [{np.min(self.grayscale_image)}, {np.max(self.grayscale_image)}]"
            )
        elif image_data.ndim == 2:
            self.grayscale_image = image_data
            min_val, max_val = float(np.min(self.grayscale_image)), float(np.max(self.grayscale_image))
            initial_wl = (max_val + min_val) / 2.0
            initial_ww = max(1.0, max_val - min_val)
            logger.info(
                f"Loaded Grayscale. Range: [{min_val}, {max_val}], Initial WL={initial_wl:.1f}, WW={initial_ww:.1f}"
            )
        else:
            logger.error("Unsupported image format.")
            self.grayscale_image = None
            self.original_image = None
            self.image_canvas.delete("all")
            self.canvas_image_item = None
            return

        self.current_wl, self.current_ww = initial_wl, initial_ww

        # Create or Re-create Histogram Widget
        if self.histogram_widget:
            self.histogram_widget.destroy()
        self.histogram_widget = Histogram(
            self.controls_frame,
            image_frame=self.grayscale_image,  # Pass grayscale data
            initial_wl=initial_wl,
            initial_ww=initial_ww,
            update_callback=self.on_histogram_update,
            width=250,
            height=150,
        )
        self.histogram_widget.pack(pady=10, padx=10, fill="x", expand=False)  # Pack below buttons

        self.update_display()  # Update display with initial WL/WW

    def apply_wlww(self, image_gray: np.ndarray, wl: float, ww: float) -> np.ndarray | None:
        """Applies WW/WL using NumPy/clip (Handles high bit depth)."""
        if image_gray is None:
            return None
        min_val = wl - ww / 2.0
        ww_safe = max(1.0, float(ww))
        image_float = image_gray.astype(np.float32)
        output_float = ((image_float - min_val) / ww_safe) * 255.0
        output_clipped = np.clip(output_float, 0, 255)
        return output_clipped.astype(np.uint8)

    def update_display(self):
        """Applies WL/WW and updates the image canvas."""
        if self.grayscale_image is None:
            if self.canvas_image_item:
                self.image_canvas.delete(self.canvas_image_item)
                self.canvas_image_item = None
            # Optionally display a "No Image" text on canvas
            # self.image_canvas.create_text(...)
            return

        display_data_8bit = self.apply_wlww(self.grayscale_image, self.current_wl, self.current_ww)
        if display_data_8bit is None:
            return

        image_pil = Image.fromarray(display_data_8bit)

        # Calculate display size based on canvas available space
        canvas_width = self.image_canvas.winfo_width()
        canvas_height = self.image_canvas.winfo_height()
        if canvas_width <= 1 or canvas_height <= 1:  # Canvas not ready yet
            # Schedule update later if needed
            # self.after(50, self.update_display)
            return

        img_w, img_h = image_pil.size
        aspect = img_w / img_h
        if aspect == 0:
            return  # Avoid division by zero

        # Scale image to fit canvas
        disp_w = canvas_width
        disp_h = int(disp_w / aspect)
        if disp_h > canvas_height:
            disp_h = canvas_height
            disp_w = int(disp_h * aspect)

        disp_w, disp_h = max(1, disp_w), max(1, disp_h)  # Ensure min size 1x1

        image_pil_resized = image_pil.resize((disp_w, disp_h), Image.Resampling.LANCZOS)
        self.photo_image = ImageTk.PhotoImage(image_pil_resized)

        # Update canvas item
        self.image_canvas.image = self.photo_image  # Keep reference
        if self.canvas_image_item:
            self.image_canvas.delete(self.canvas_image_item)
        self.canvas_image_item = self.image_canvas.create_image(0, 0, anchor="nw", image=self.photo_image)
        # Update canvas size to potentially fit resized image? Optional.
        # self.image_canvas.config(width=disp_w, height=disp_h)

    def on_histogram_update(self, wl: float, ww: float):
        """Callback function called by Histogram when user interacts with it."""
        self.current_wl = wl
        self.current_ww = ww
        self.update_display()  # Update main image when histogram changes

    def on_resize(self, event=None):
        """Handle window resize - redraw image."""
        # Debounce resize slightly
        if hasattr(self, "_app_resize_debounce"):
            self.after_cancel(self._app_resize_debounce)
        self._app_resize_debounce = self.after(100, self.update_display)

    # --- Sample Loading ---
    def load_grayscale_sample(self):
        print("Loading 16-bit Grayscale...")
        self.load_image(self.generate_grayscale_16bit())

    def load_rgb_sample(self):
        print("Loading RGB Sample...")
        self.load_image(self.generate_rgb_sample())

    # --- Sample Data Generation ---
    @staticmethod
    def generate_grayscale_16bit(size=512):
        x = np.linspace(0, 4095, size, dtype=np.float32)
        y = np.linspace(-1000, 1000, size, dtype=np.float32)
        xx, yy = np.meshgrid(x, y)
        image = (xx + yy).astype(np.int16)  # Use int16 for +/- range
        cx, cy, bs = size // 2, size // 2, size // 8
        image[cy - bs : cy + bs, cx - bs : cx + bs] = 3000  # High density
        image[bs : bs * 2, bs : bs * 2] = -500
        return image  # Low density

    @staticmethod
    def generate_rgb_sample(size=512):
        image = np.zeros((size, size, 3), dtype=np.uint8)
        image[:, :, 0] = np.tile(np.linspace(0, 255, size), (size, 1)).astype(np.uint8)
        image[:, :, 1] = np.tile(np.linspace(0, 255, size), (size, 1)).T.astype(np.uint8)
        cx, cy, r = size // 2, size // 2, size // 4
        y, x = np.ogrid[:size, :size]
        mask = (x - cx) ** 2 + (y - cy) ** 2 <= r**2
        image[mask, 2] = 200
        return image


# --- Run Application ---
if __name__ == "__main__":
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")
    app = SimpleImageViewer()
    app.mainloop()
