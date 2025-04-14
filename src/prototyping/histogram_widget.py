import customtkinter as ctk
import numpy as np
import tkinter as tk
from PIL import Image, ImageTk  # Pillow for image handling

# --- Configuration (Updated Colors) ---
DEFAULT_NUM_BINS = 256
HISTOGRAM_BAR_COLOR = ("gray70", "gray30")  # Keep neutral histogram bars
WL_LINE_COLOR = "black"
WW_BOUNDARY_LINE_COLOR = "black"  # Color for WW boundary lines
AXIS_LABEL_COLOR = ("gray10", "gray90")  # Color for min/max labels


# --- Histogram Widget (Modified) ---
class CTkHistogramWidget(ctk.CTkFrame):
    """
    A CustomTkinter widget to display an image histogram and allow
    interactive adjustment of Window Level (WL) and Window Width (WW)
    indicated by superimposed lines. Includes min/max intensity labels.
    """

    def __init__(self, master, width=300, height=150, num_bins=DEFAULT_NUM_BINS, callback=None, *args, **kwargs):
        super().__init__(master, *args, **kwargs)

        self.widget_width = width
        self.widget_height = height
        self.num_bins = num_bins
        self.update_callback = callback

        self.hist_data = np.array([])
        self.bin_edges = np.array([])
        self.image_min_intensity = 0.0
        self.image_max_intensity = 255.0
        self.max_hist_count = 1

        self._current_wl = tk.DoubleVar(value=128.0)
        self._current_ww = tk.DoubleVar(value=256.0)

        self._is_left_dragging = False
        self._is_right_dragging = False
        self._drag_start_x = 0
        self._drag_start_wl = 0.0
        self._drag_start_ww = 1.0

        # --- Widget Layout ---
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        self.hist_canvas = ctk.CTkCanvas(
            self,
            width=self.widget_width - 20,
            height=self.widget_height - 40,
            background=self._apply_appearance_mode(ctk.ThemeManager.theme["CTkFrame"]["fg_color"]),
            borderwidth=0,
            highlightthickness=0,
        )
        self.hist_canvas.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="nsew")

        self.label_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.label_frame.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="ew")
        self.label_frame.grid_columnconfigure((0, 1), weight=1)

        self.wl_label = ctk.CTkLabel(self.label_frame, text="WL: ---", anchor="w")
        self.wl_label.grid(row=0, column=0, sticky="w")

        self.ww_label = ctk.CTkLabel(self.label_frame, text="WW: ---", anchor="e")
        self.ww_label.grid(row=0, column=1, sticky="e")

        # --- Bind Mouse Events ---
        self.hist_canvas.bind("<ButtonPress-1>", self._on_left_press)
        self.hist_canvas.bind("<B1-Motion>", self._on_left_drag)
        self.hist_canvas.bind("<ButtonRelease-1>", self._on_left_release)
        self.hist_canvas.bind("<ButtonPress-3>", self._on_right_press)
        self.hist_canvas.bind("<B3-Motion>", self._on_right_drag)
        self.hist_canvas.bind("<ButtonRelease-3>", self._on_right_release)
        self.bind("<Configure>", self._on_configure, add=True)

    # --- Public Methods ---
    def update_image(self, image_frame: np.ndarray):
        """Updates histogram with data from a new image frame (expects grayscale)."""
        if image_frame is None or image_frame.size == 0 or image_frame.ndim != 2:
            self.hist_data = np.zeros(self.num_bins)
            self.bin_edges = np.linspace(0, 255, self.num_bins + 1)
            self.image_min_intensity = 0.0
            self.image_max_intensity = 255.0
            self.max_hist_count = 1
            self._current_wl.set(128.0)
            self._current_ww.set(256.0)
            print("Warning: Histogram requires 2D grayscale image data.")
        else:
            self._calculate_histogram(image_frame)
            initial_wl = (self.image_max_intensity + self.image_min_intensity) / 2.0
            initial_ww = max(1.0, self.image_max_intensity - self.image_min_intensity)
            self._current_wl.set(initial_wl)
            self._current_ww.set(initial_ww)
        self._redraw()
        self._update_labels()

    def set_wlww(self, wl: float, ww: float):
        """Programmatically sets the Window Level and Window Width."""
        ww_clamped = max(1.0, ww)
        self._current_wl.set(wl)
        self._current_ww.set(ww_clamped)
        self._redraw()
        self._update_labels()

    def get_wlww(self) -> tuple[float, float]:
        """Gets the current Window Level and Window Width."""
        return self._current_wl.get(), self._current_ww.get()

    # --- Internal Calculation and Drawing Methods ---
    def _calculate_histogram(self, image_frame: np.ndarray):
        """Calculates histogram data and intensity range."""
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
        """Clears and redraws the entire canvas content."""
        hist_bg_color = self._apply_appearance_mode(ctk.ThemeManager.theme["CTkFrame"]["fg_color"])
        self.hist_canvas.configure(background=hist_bg_color)
        self.hist_canvas.delete("all")

        # Draw components in order
        self._draw_histogram_bars()
        self._draw_wlww_indicators()
        self._draw_axis_labels()  # Add axis labels

    def _draw_histogram_bars(self):
        """Draws the histogram bars on the main canvas."""
        canvas_width = self.hist_canvas.winfo_width()
        canvas_height = self.hist_canvas.winfo_height()
        if canvas_width <= 1 or canvas_height <= 1 or len(self.hist_data) == 0:
            return
        bar_color = self._apply_appearance_mode(HISTOGRAM_BAR_COLOR)
        for i in range(self.num_bins):
            x0 = self._intensity_to_x(self.bin_edges[i], canvas_width)
            x1 = self._intensity_to_x(self.bin_edges[i + 1], canvas_width)
            # Leave a small gap at the bottom for axis labels
            bar_area_height = canvas_height - 15
            if bar_area_height <= 0:
                bar_area_height = canvas_height  # Prevent negative height
            bar_height_normalized = (self.hist_data[i] / self.max_hist_count) * (bar_area_height * 0.98)
            y0 = bar_area_height - bar_height_normalized
            y1 = bar_area_height  # Draw bars ending just above the label area
            if x1 <= x0:
                x1 = x0 + 1
            self.hist_canvas.create_rectangle(x0, y0, x1, y1, fill=bar_color, outline="", tags="histogram_bar")

    def _draw_wlww_indicators(self):
        """Draws the WL line and WW boundary lines superimposed on the histogram canvas."""
        canvas_width = self.hist_canvas.winfo_width()
        canvas_height = self.hist_canvas.winfo_height()
        if canvas_width <= 1 or canvas_height <= 1:
            return

        # Reduce height slightly to avoid overlapping axis labels
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

        # Draw WW Boundary Lines
        self.hist_canvas.create_line(
            ww_min_x,
            0,
            ww_min_x,
            indicator_height,  # Use indicator_height
            fill=WW_BOUNDARY_LINE_COLOR,
            width=1,
            dash=(4, 4),
            tags="ww_line",
        )
        self.hist_canvas.create_line(
            ww_max_x,
            0,
            ww_max_x,
            indicator_height,  # Use indicator_height
            fill=WW_BOUNDARY_LINE_COLOR,
            width=1,
            dash=(4, 4),
            tags="ww_line",
        )
        # Draw WL line on top
        self.hist_canvas.create_line(
            wl_x,
            0,
            wl_x,
            indicator_height,  # Use indicator_height
            fill=WL_LINE_COLOR,
            width=2,
            tags="wl_line",
        )

    def _draw_axis_labels(self):
        """Draws the min and max intensity labels on the x-axis."""
        canvas_width = self.hist_canvas.winfo_width()
        canvas_height = self.hist_canvas.winfo_height()
        if canvas_width <= 1 or canvas_height <= 1:
            return

        label_y = canvas_height - 5  # Position labels near the bottom
        label_color = self._apply_appearance_mode(AXIS_LABEL_COLOR)
        label_font = ctk.CTkFont(size=10)  # Use a smaller font

        # Min Label
        min_text = f"{self.image_min_intensity:.0f}"
        self.hist_canvas.create_text(
            5,
            label_y,  # Position bottom-left with padding
            text=min_text,
            anchor="sw",  # Anchor South-West
            fill=label_color,
            font=label_font,
            tags="axis_label",
        )

        # Max Label
        max_text = f"{self.image_max_intensity:.0f}"
        self.hist_canvas.create_text(
            canvas_width - 5,
            label_y,  # Position bottom-right with padding
            text=max_text,
            anchor="se",  # Anchor South-East
            fill=label_color,
            font=label_font,
            tags="axis_label",
        )

    # _update_labels, coordinate mapping, event handlers remain the same
    def _update_labels(self):
        wl = self._current_wl.get()
        ww = self._current_ww.get()
        self.wl_label.configure(text=f"WL: {wl:.1f}")
        self.ww_label.configure(text=f"WW: {ww:.1f}")

    def _intensity_to_x(self, intensity: float, canvas_width: int) -> float:
        if canvas_width == 0:
            return 0.0
        intensity_range = self.image_max_intensity - self.image_min_intensity
        if intensity_range == 0:
            return 0.0
        normalized_intensity = (intensity - self.image_min_intensity) / intensity_range
        x = normalized_intensity * canvas_width
        return max(0.0, min(float(canvas_width), x))

    def _x_to_intensity(self, x_coordinate: float, canvas_width: int) -> float:
        if canvas_width == 0:
            return self.image_min_intensity
        normalized_x = x_coordinate / canvas_width
        intensity = self.image_min_intensity + normalized_x * (self.image_max_intensity - self.image_min_intensity)
        return max(self.image_min_intensity, min(self.image_max_intensity, intensity))

    def _on_configure(self, event=None):
        self.after_idle(self._redraw)

    def _on_left_press(self, event):
        self._is_left_dragging = True
        self._drag_start_x = event.x
        self._drag_start_wl = self._current_wl.get()
        new_wl = self._x_to_intensity(event.x, self.hist_canvas.winfo_width())
        self._current_wl.set(new_wl)
        self._redraw()
        self._update_labels()
        if self.update_callback:
            self.update_callback(self._current_wl.get(), self._current_ww.get())

    def _on_left_drag(self, event):
        if not self._is_left_dragging:
            return
        new_wl = self._x_to_intensity(event.x, self.hist_canvas.winfo_width())
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
        canvas_width = self.hist_canvas.winfo_width()
        if canvas_width == 0:
            return
        delta_x = event.x - self._drag_start_x
        intensity_range = self.image_max_intensity - self.image_min_intensity
        if intensity_range == 0:
            return
        sensitivity_factor = 1.5
        delta_ww = (delta_x / canvas_width) * intensity_range * sensitivity_factor
        new_ww = self._drag_start_ww + delta_ww
        new_ww = max(1.0, new_ww)
        self._current_ww.set(new_ww)
        self._redraw()
        self._update_labels()
        if self.update_callback:
            self.update_callback(self._current_wl.get(), self._current_ww.get())

    def _on_right_release(self, event):
        self._is_right_dragging = False


# --- Simple Image Viewer Application (code mostly unchanged) ---
class SimpleImageViewer(ctk.CTk):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.title("Simple Image Viewer")
        self.geometry("800x600")

        # --- State ---
        self.original_image = None
        self.grayscale_image = None
        self.current_wl = 128.0
        self.current_ww = 256.0
        self.display_size = (500, 500)

        # --- Layout ---
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(0, weight=1)

        self.image_label = ctk.CTkLabel(
            self, text="Load an image", width=self.display_size[0], height=self.display_size[1]
        )
        self.image_label.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        self.controls_frame = ctk.CTkFrame(self)
        self.controls_frame.grid(row=0, column=1, padx=10, pady=10, sticky="ns")

        self.histogram_widget = CTkHistogramWidget(
            self.controls_frame,
            callback=self.on_histogram_update,
            width=250,
            height=150,  # Ensure enough height for labels
        )
        self.histogram_widget.pack(pady=10, padx=10, fill="x")

        self.load_grayscale_button = ctk.CTkButton(
            self.controls_frame, text="Load 16-bit Grayscale", command=self.load_grayscale_sample
        )
        self.load_grayscale_button.pack(pady=5, padx=10, fill="x")

        self.load_rgb_button = ctk.CTkButton(self.controls_frame, text="Load RGB Sample", command=self.load_rgb_sample)
        self.load_rgb_button.pack(pady=5, padx=10, fill="x")

    # --- Image Handling Methods ---
    def load_image(self, image_data: np.ndarray):
        self.original_image = image_data
        if image_data.ndim == 3 and image_data.shape[2] == 3:  # RGB
            pil_img = Image.fromarray(image_data)
            pil_gray = pil_img.convert("L")
            self.grayscale_image = np.array(pil_gray)
            print(
                f"Loaded RGB image, converted to grayscale (Min: {np.min(self.grayscale_image)}, Max: {np.max(self.grayscale_image)})"
            )
        elif image_data.ndim == 2:  # Grayscale
            self.grayscale_image = image_data
            print(f"Loaded Grayscale image (Min: {np.min(self.grayscale_image)}, Max: {np.max(self.grayscale_image)})")
        else:
            print("Error: Unsupported image format.")
            self.grayscale_image = None
            self.original_image = None
            self.image_label.configure(text="Unsupported format", image=None)
            self.histogram_widget.update_image(np.array([]))
            return
        # Pass grayscale to histogram
        self.histogram_widget.update_image(self.grayscale_image)
        # Get initial WL/WW from histogram
        self.current_wl, self.current_ww = self.histogram_widget.get_wlww()
        # Update display using initial WL/WW
        self.update_display()

    def apply_wlww(self, image_gray: np.ndarray, wl: float, ww: float) -> np.ndarray:
        if image_gray is None:
            return None
        min_val = wl - ww / 2.0
        max_val = wl + ww / 2.0
        # Use float64 for calculations to avoid overflow/underflow with high bit depth
        windowed_image = image_gray.astype(np.float64, copy=True)
        windowed_image[windowed_image < min_val] = min_val
        windowed_image[windowed_image > max_val] = max_val
        if ww > 0:
            # Scale to 0-255 range
            scaled_image = ((windowed_image - min_val) / ww) * 255.0
        else:  # Handle WW=0 case
            scaled_image = np.full_like(windowed_image, 128.0)
            scaled_image[windowed_image < wl] = 0.0
            scaled_image[windowed_image > wl] = 255.0
        # Clamp final values just in case of floating point inaccuracies
        scaled_image[scaled_image < 0] = 0
        scaled_image[scaled_image > 255] = 255
        # Convert to uint8 for display
        output_image = scaled_image.astype(np.uint8)
        return output_image

    def update_display(self):
        if self.grayscale_image is None:
            self.image_label.configure(text="No image loaded", image=None)
            return
        display_data_8bit = self.apply_wlww(self.grayscale_image, self.current_wl, self.current_ww)
        if display_data_8bit is None:
            self.image_label.configure(text="Error applying WL/WW", image=None)
            return
        pil_image = Image.fromarray(display_data_8bit)
        pil_image.thumbnail(self.display_size, Image.Resampling.LANCZOS)
        ctk_image = ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=(pil_image.width, pil_image.height))
        self.image_label.configure(image=ctk_image, text="")

    # --- Callback ---
    def on_histogram_update(self, wl: float, ww: float):
        self.current_wl = wl
        self.current_ww = ww
        self.update_display()

    # --- Sample Loading ---
    def load_grayscale_sample(self):
        print("Loading 16-bit Grayscale Sample...")
        self.load_image(self.generate_grayscale_16bit())

    def load_rgb_sample(self):
        print("Loading RGB Sample...")
        self.load_image(self.generate_rgb_sample())

    # --- Sample Data Generation (Static Methods) ---
    @staticmethod
    def generate_grayscale_16bit(size=512):
        image = np.zeros((size, size), dtype=np.uint16)
        x = np.linspace(0, 1000, size)
        y = np.linspace(0, 1500, size)
        xx, yy = np.meshgrid(x, y)
        image = (xx + yy).astype(np.uint16)
        center_x, center_y = size // 2, size // 2
        block_size = size // 8
        image[center_y - block_size : center_y + block_size, center_x - block_size : center_x + block_size] = 4000
        image[block_size : block_size * 2, block_size : block_size * 2] = 100
        return image

    @staticmethod
    def generate_rgb_sample(size=512):
        image = np.zeros((size, size, 3), dtype=np.uint8)
        image[:, :, 0] = np.tile(np.linspace(0, 255, size), (size, 1)).astype(np.uint8)
        image[:, :, 1] = np.tile(np.linspace(0, 255, size), (size, 1)).T.astype(np.uint8)
        center_x, center_y = size // 2, size // 2
        radius = size // 4
        y, x = np.ogrid[:size, :size]
        mask = (x - center_x) ** 2 + (y - center_y) ** 2 <= radius**2
        image[mask, 2] = 200
        return image


# --- Run Application ---
if __name__ == "__main__":
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")
    app = SimpleImageViewer()
    app.load_grayscale_sample()  # Load initial image
    app.mainloop()
