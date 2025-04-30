import gc
import logging
import tkinter as tk
from tkinter import ttk
from typing import Callable

import customtkinter as ctk
import cv2
import numpy as np
from PIL import Image, ImageTk

from anonymizer.controller.create_projections import apply_windowing
from anonymizer.controller.remove_pixel_phi import LayerType, OCRText, OverlayData, Segmentation, UserRectangle
from anonymizer.utils.translate import _
from anonymizer.view.histogram import Histogram

logger = logging.getLogger(__name__)


class ImageViewer(ctk.CTkFrame):
    CACHE_SIZE = 50  # Maximum number of images to keep in cache
    MIN_FPS = 1
    NORMAL_FPS = 5
    MAX_FPS = 20
    PRELOAD_FRAMES = 10  # Number of frames to preload
    PLAY_BTN_SIZE = (32, 32)
    BUTTON_WIDTH = 100
    PAD = 10
    SMALL_JUMP_PERCENTAGE = 0.01  # 1% of the total images
    LARGE_JUMP_PERCENTAGE = 0.10  # 10% of the total images
    MAX_SCREEN_PERCENTAGE = 0.7  # area of current screen available for displaying image
    TEXT_BOX_COLOR = (0, 255, 0)  # RGB = green
    USER_RECT_COLOR = (0, 0, 255)  # RGB = blue
    SEGMENTATION_COLOR = (255, 0, 0)  # RGB = red
    DEFAULT_WL_SENSITIVITY = 0.75  # Pixels moved per unit change in WL (affects Beta)
    DEFAULT_WW_SENSITIVITY = 0.75  # Pixels moved per unit change in WW (affects Alpha)

    def __init__(
        self,
        parent,
        images: np.ndarray,
        initial_wl: float,
        initial_ww: float,
        add_to_whitelist_callback: Callable[[str], None] | None = None,
        regenerate_series_projections_callback: Callable[[], None] | None = None,
    ):
        super().__init__(master=parent)  # Call the superclass constructor
        self.parent = parent

        if images is None or images.size == 0:
            raise ValueError("ImageViewer requires a non-empty NumPy array for images.")
        if images.ndim not in [3, 4]:  # Expect (F, H, W) or (F, H, W, C)
            raise ValueError(f"Unsupported image array dimensions: {images.ndim}. Expected 3 or 4.")

        self.num_images: int = images.shape[0]
        self.images: np.ndarray = images
        self.add_to_whitelist_callback = add_to_whitelist_callback
        self.regenerate_series_projections_callback = regenerate_series_projections_callback

        # Determine image properties from the last frame
        last_frame = images[-1]
        self.image_height: int = last_frame.shape[0]
        self.image_width: int = last_frame.shape[1]

        # --- Determine if series is high bit depth grayscale ---
        self.is_high_bit_grayscale: bool = (last_frame.ndim == 2 and last_frame.dtype != np.uint8) or (
            last_frame.ndim == 3 and last_frame.shape[-1] == 1 and last_frame.dtype != np.uint8
        )
        self.is_color: bool = last_frame.ndim == 3 and last_frame.shape[2] == 3

        logger.info(
            f"ImageViewer Init: HighBitGrayscale={self.is_high_bit_grayscale}, Color={self.is_color}, Dtype={last_frame.dtype}, Shape={images.shape}"
        )

        self.current_image_index: int = 0
        # Cache for loaded images: cache index: (PhotoImage, (Width, Height))
        self.image_cache: dict[int, tuple[ImageTk.PhotoImage, Image.Image, tuple[int, int]]] = {}
        self.fps: int = self.NORMAL_FPS  # Frames per second for playback
        self.playing: bool = False  # Playback state
        self.play_delay: int = int(1000 / self.fps)  # Delay in milliseconds, initial value
        self.after_id = None  # Store the ID of the 'after' call
        self.current_size: tuple[int, int] = (images.shape[2], images.shape[1])
        self.overlay_data: dict[int, OverlayData] = {}  # Store overlay data per frame
        self.propagate_overlays: bool = False
        self.active_layers: set[LayerType] = set()
        self.active_layers.add(LayerType.TEXT)
        self.active_layers.add(LayerType.USER_RECT)

        # --- User Rectangle Tracking ---
        self.temp_rect_id = None
        self.drawing_rect = False
        self.start_x = None
        self.start_y = None

        # --- Windowing: Brightness/Contrast Tracking --
        self.adjusting_wlww: bool = False
        self.adjust_start_x: int | None = None
        self.adjust_start_y: int | None = None
        # Set initial WW/WL
        self.current_wl: float = initial_wl
        self.current_ww: float = initial_ww
        self.initial_wl: float = initial_wl
        self.initial_ww: float = initial_ww
        # Derived alpha/beta for internal use with convertScaleAbs
        self._derived_alpha: float = 1.0
        self._derived_beta: int = 0
        self._update_derived_alpha_beta()  # Calculate initial derived values

        # --- Calculate Jump Amounts Dynamically ---
        self.small_jump: int = max(1, int(self.num_images * self.SMALL_JUMP_PERCENTAGE))  # Ensure at least 1
        self.large_jump: int = max(1, int(self.num_images * self.LARGE_JUMP_PERCENTAGE))

        # --- Load Button Icons ---
        # Load images and convert to Pillow Image
        play_image = Image.open("assets/icons/play.png").resize(self.PLAY_BTN_SIZE)
        pause_image = Image.open("assets/icons/pause.png").resize(self.PLAY_BTN_SIZE)

        # --- Create Play/Pause Icons as CTkImage objects ---
        self.ctk_play_icon = ctk.CTkImage(light_image=play_image, dark_image=play_image, size=self.PLAY_BTN_SIZE)
        self.ctk_pause_icon = ctk.CTkImage(light_image=pause_image, dark_image=pause_image, size=self.PLAY_BTN_SIZE)

        # --- UI Elements ---
        # --- Grid Layout ---
        self.grid_rowconfigure(0, weight=1)  # Image label row expands
        self.grid_columnconfigure(0, weight=1)  # Image label column expands

        # Image Frame:
        self.image_frame = ctk.CTkFrame(self)
        self.image_frame.grid(row=0, column=0, sticky="nsew")
        self.image_frame.grid_rowconfigure(0, weight=1)  # Image label row expands
        self.image_frame.grid_columnconfigure(0, weight=1)  # Image label column expands

        # Canvas (holds current frame pixels)
        self.canvas = tk.Canvas(self.image_frame, bg="black", borderwidth=0, highlightthickness=0)
        self.canvas_image_item = None  # Add this attribute to store the ID of the image on the canvas
        self.canvas.grid(row=0, column=0, sticky="nsew")

        # Scrollbar
        if self.num_images > 1:
            self.scrollbar = ttk.Scrollbar(self.image_frame, orient=ctk.HORIZONTAL, command=self.scroll_handler)
            self.scrollbar.grid(row=1, column=0, sticky="ew")  # sticky="ew"
            self.update_scrollbar()

        # Data Frame:
        self.data_frame = ctk.CTkFrame(self)
        self.data_frame.grid(row=0, column=1, padx=self.PAD, pady=self.PAD, sticky="ns")
        self.data_frame.grid_rowconfigure(0, weight=1)

        # Histogram: (histogram is displayed after layout finalised)
        self.histogram = Histogram(
            self.data_frame,
            update_callback=self._handle_histogram_update,
        )
        self.histogram.set_wlww(self.current_wl, self.current_ww, redraw=False)
        self.histogram.grid(row=0, column=1, padx=self.PAD, pady=self.PAD, sticky="n")

        # Control Frame for fixed width widgets
        self.control_frame = ctk.CTkFrame(self.data_frame)
        self.control_frame.grid(row=1, column=1, padx=self.PAD, pady=self.PAD, sticky="ew")
        self.control_frame.grid_columnconfigure(1, weight=1)

        # Image Size Label:
        self.image_size_label = ctk.CTkLabel(self.control_frame, text="")
        self.image_size_label.grid(row=0, column=0, sticky="w", padx=self.PAD)

        self.projection_label = ctk.CTkLabel(self.control_frame, text="")
        self.projection_label.grid(row=1, column=0, sticky="w", padx=self.PAD)

        # --- Toggle Button (Play/Pause) for multi-frame series ---
        if self.num_images > 1:
            self.fps_slider = ctk.CTkSlider(
                self.control_frame,
                width=self.BUTTON_WIDTH,
                from_=self.MIN_FPS,
                to=self.MAX_FPS,
                number_of_steps=self.MAX_FPS - self.MIN_FPS,
                orientation=ctk.HORIZONTAL,
                command=lambda value: self.change_fps(value),
            )
            self.fps_slider.set(self.fps)
            self.fps_slider.grid(row=1, column=2, padx=self.PAD)

            self.fps_slider_label = ctk.CTkLabel(self.control_frame, text=f"{self.fps} fps")
            self.fps_slider_label.grid(row=0, column=2, padx=self.PAD)

            self.toggle_button = ctk.CTkButton(
                self.control_frame,
                text="",
                image=self.ctk_play_icon,
                width=self.PLAY_BTN_SIZE[0],
                command=self.toggle_play,
            )
            self.toggle_button.grid(row=0, column=3, padx=self.PAD, pady=(self.PAD, 0), sticky="e")

        self.image_number_label = ctk.CTkLabel(self.control_frame, text="", font=("Courier Bold", 14))
        self.image_number_label.grid(row=1, column=3, sticky="s", padx=(0, self.PAD))

        # Event binding:
        # Mouse:
        self.bind("<Configure>", self.on_resize)
        self.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<Button-1>", self._on_left_click)  # Left-click press
        self.canvas.bind("<B1-Motion>", self.draw_box)  # Left-click drag
        self.canvas.bind("<ButtonRelease-1>", self.end_drawing_user_rect)  # Left-click release
        self.canvas.bind("<ButtonPress-3>", self._start_adjust_display)  # Right-click press
        self.canvas.bind("<B3-Motion>", self._adjust_display)  # Right-click drag
        self.canvas.bind("<ButtonRelease-3>", self._end_adjust_display)  # Right-click release
        if self.num_images > 1:
            self.control_frame.bind("<MouseWheel>", self.on_mousewheel)

        # Keys:
        # Note: customtkinter key bindings bind to the canvas of the frame
        # see here: https://stackoverflow.com/questions/77676235/tkinter-focus-set-on-frame
        if self.num_images > 1:
            self.bind("<Left>", self.prev_image)
            self.bind("<Right>", self.next_image)
            self.bind("<Up>", self.change_image_up)
            self.bind("<Down>", self.change_image_down)
            self.bind("<Prior>", self.change_image_prior)
            self.bind("<Next>", self.change_image_next)
            self.bind("<Home>", self.change_image_home)
            self.bind("<End>", self.change_image_end)
            self.bind("<space>", self.toggle_play)

        # Focus management for ImageViewer
        self.bind("<Enter>", self.mouse_enter)
        self.canvas.bind("<Enter>", self.mouse_enter)
        self.control_frame.bind("<Enter>", self.mouse_enter)

        self.after_idle(self._set_initial_size)
        self.update_status()

    def get_current_image(self) -> np.ndarray:
        return self.images[self.current_image_index]

    def set_overlay_propagation(self, propagate: bool):
        self.propagate_overlays = propagate

    def set_text_overlay_data(self, frame_index: int, data: list[OCRText]):
        # Creates new text overlay if one doesn't exist yet:
        if frame_index not in self.overlay_data:
            self.overlay_data[frame_index] = OverlayData()

        self.overlay_data[frame_index].ocr_texts = data

        if frame_index == self.current_image_index:  # update display
            self.remove_from_cache(frame_index)  # force re-rendering
            self.load_and_display_image(self.current_image_index)

    def get_text_overlay_data(self, frame_index: int) -> list[OCRText] | None:
        """Retrieves the text overlay data for a specific frame."""
        if frame_index not in self.overlay_data:
            return None
        return self.overlay_data[frame_index].ocr_texts

    def set_segmentation_overlay_data(self, frame_index: int, data: list[Segmentation]):
        if frame_index not in self.overlay_data:
            self.overlay_data[frame_index] = OverlayData()
        self.overlay_data[frame_index].segmentations = data
        if frame_index == self.current_image_index:  # update display
            self.remove_from_cache(frame_index)  # force re-rendering
            self.load_and_display_image(self.current_image_index)

    def get_segmentation_overlay_data(self, frame_index: int) -> list[Segmentation] | None:
        """Retrieves the segmentation overlay data for a specific frame."""
        if frame_index not in self.overlay_data:
            return None
        return self.overlay_data[frame_index].segmentations

    def set_user_rectangle_overlay_data(self, frame_index: int, data: list[UserRectangle]):
        """Sets the user rectangle overlay data for a specific frame."""
        if frame_index not in self.overlay_data:
            self.overlay_data[frame_index] = OverlayData()
        self.overlay_data[frame_index].user_rects = data
        if frame_index == self.current_image_index:  # update display
            self.remove_from_cache(frame_index)  # force re-rendering
            self.load_and_display_image(self.current_image_index)

    def get_user_rectangle_overlay_data(self, frame_index: int) -> list[UserRectangle] | None:
        """Retrieves the user rectangle overlay data for a specific frame."""
        if frame_index not in self.overlay_data:
            return None
        return self.overlay_data[frame_index].user_rects

    def _image_to_view_coords(self, x: int, y: int) -> tuple[int, int]:
        """Converts image coordinates to view (display) coordinates."""
        image_width = self.images.shape[2]
        image_height = self.images.shape[1]
        scale_x = self.current_size[0] / image_width
        scale_y = self.current_size[1] / image_height
        return int(x * scale_x), int(y * scale_y)

    def _view_to_image_coords(self, x: int, y: int) -> tuple[int, int]:
        """Converts view (display) coordinates to image coordinates."""
        image_width = self.images.shape[2]
        image_height = self.images.shape[1]
        scale_x = self.current_size[0] / image_width
        scale_y = self.current_size[1] / image_height
        # Avoid division by zero. If scale is zero, return original coords (or handle appropriately).
        if scale_x == 0 or scale_y == 0:
            return x, y
        return int(x / scale_x), int(y / scale_y)

    def _calculate_scaled_size(self, max_width: int, max_height: int) -> tuple[int, int]:
        """Calculates the scaled size, preserving aspect ratio."""
        aspect_ratio = self.image_width / self.image_height
        if self.image_width > max_width or self.image_height > max_height:
            if self.image_width / max_width > self.image_height / max_height:
                new_width = max_width
                new_height = int(new_width / aspect_ratio)
            else:
                new_height = max_height
                new_width = int(new_height * aspect_ratio)
            return new_width, new_height
        else:
            return self.image_width, self.image_height

    def toggle_layer(self, layer_name: LayerType, is_active: bool):
        if is_active:
            self.active_layers.add(layer_name)
        else:
            self.active_layers.discard(layer_name)
        self.load_and_display_image(self.current_image_index)

    def refresh_current_image(self):
        self.remove_from_cache(self.current_image_index)  # Use the method that closes PIL image
        self.load_and_display_image(self.current_image_index)

    def mouse_enter(self, event):
        logger.debug("mouse_enter")
        self._canvas.focus_set()

    def _set_initial_size(self):
        """Calculates and sets the initial image size based on screen size."""
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        max_width = int(screen_width * self.MAX_SCREEN_PERCENTAGE)
        max_height = int(screen_height * self.MAX_SCREEN_PERCENTAGE)

        self.current_size = self._calculate_scaled_size(max_width, max_height)
        self.canvas.config(width=self.current_size[0], height=self.current_size[1])
        self.load_and_display_image(0)
        self.histogram.update_image(self.images[0])
        self._canvas.focus_set()

    def _handle_histogram_update(self, wl: float, ww: float):
        """Callback function called by Histogram widget when WL/WW changes interactively."""
        logger.debug(f"Received WL/WW update from histogram: WL={wl:.1f}, WW={ww:.1f}")
        # Update ImageViewer's master state
        wl_changed = abs(wl - self.current_wl) > 0.01
        ww_clamped = max(1.0, ww)  # Ensure WW is valid
        ww_changed = abs(ww_clamped - self.current_ww) > 0.01

        if wl_changed or ww_changed:
            self.current_wl = wl
            self.current_ww = ww_clamped
            # Trigger a redraw of the main image viewer
            self.refresh_current_image()  # Use refresh to force reload

    def update_status(self):
        self.projection_label.configure(text=self.get_projection_label())
        self.image_number_label.configure(text=f"{self.current_image_index + 1}/{self.num_images}")
        self.image_size_label.configure(
            text=f"View[{self.current_size[0]}x{self.current_size[1]}] Actual[{self.images.shape[2]}x{self.images.shape[1]}]"
        )

    def get_projection_label(self) -> str:
        if self.num_images == 1:
            return ""
        match self.current_image_index:
            case 0:
                return _("MIN PROJECTION")
            case 1:
                return _("MEAN PROJECTION")
            case 2:
                return _("MAX PROJECTION")
            case _:
                return ""

    def _render_overlays(self, frame_ndx: int) -> np.ndarray:
        """Renders all active overlays for specified frame."""

        combined_overlay = np.zeros((self.image_height, self.image_width, 3), dtype=np.uint8)
        if frame_ndx not in self.overlay_data:
            return combined_overlay

        overlay_data: OverlayData = self.overlay_data[frame_ndx]

        for layer_name in self.active_layers:
            if layer_name == LayerType.TEXT and overlay_data.ocr_texts:
                for text_data in overlay_data.ocr_texts:
                    x1, y1, x2, y2 = text_data.get_bounding_box()
                    cv2.rectangle(combined_overlay, (x1, y1), (x2, y2), self.TEXT_BOX_COLOR, 2)

            elif layer_name == LayerType.SEGMENTATIONS and overlay_data.segmentations:
                # TODO: segment annotation creation and display
                for segmentation in overlay_data.segmentations:
                    points = np.array([(p.x, p.y) for p in segmentation.points], dtype=np.int32)
                    cv2.fillPoly(combined_overlay, [points], (255, 0, 0))  # Filled red

        # Iterate through the layers that are currently active/visible
        for layer_name in self.active_layers:
            match layer_name:
                case LayerType.TEXT:
                    if overlay_data.ocr_texts:
                        for text_data in overlay_data.ocr_texts:
                            x1, y1, x2, y2 = text_data.get_bounding_box()
                            cv2.rectangle(combined_overlay, (x1, y1), (x2, y2), self.TEXT_BOX_COLOR, 2)

                case LayerType.USER_RECT:
                    if overlay_data.user_rects:
                        for rect in overlay_data.user_rects:
                            x1, y1, x2, y2 = rect.get_bounding_box()
                            cv2.rectangle(combined_overlay, (x1, y1), (x2, y2), self.USER_RECT_COLOR, 2)

                case LayerType.SEGMENTATIONS:
                    if overlay_data.segmentations:
                        for segmentation in overlay_data.segmentations:
                            points = np.array([(p.x, p.y) for p in segmentation.points], dtype=np.int32)
                            # Example: Draw filled green polygons for segmentations
                            cv2.fillPoly(combined_overlay, [points], self.SEGMENTATION_COLOR)

                case _:
                    # Handle unknown layer types if necessary
                    logger.warning(f"Rendering not implemented for layer type: {layer_name}")

        return combined_overlay

    def load_and_display_image(self, frame_ndx: int):
        logger.debug(f"Loading and displaying image at index: {frame_ndx}")
        if not (0 <= frame_ndx < self.num_images) or self.images is None:
            logger.error(f"Invalid frame index: {frame_ndx}")
            return

        # Use Cache:
        if frame_ndx in self.image_cache:
            cached_image, __, cached_size = self.image_cache[frame_ndx]
            if cached_size == self.current_size:
                self.photo_image = cached_image
                self.canvas.image = self.photo_image  # type: ignore # Keep a reference, crucially important for Tkinter.
                if self.canvas_image_item:
                    self.canvas.delete(self.canvas_image_item)
                self.canvas_image_item = self.canvas.create_image(0, 0, anchor="nw", image=self.photo_image)
                if self.current_image_index != frame_ndx:
                    self.histogram.update_image(self.images[frame_ndx])
                self.current_image_index = frame_ndx
                self.update_scrollbar()
                self.update_status()
                return

        image_array = self.images[frame_ndx].copy()

        # Update Histogram Data if frame change:
        if self.current_image_index != frame_ndx:
            self.histogram.update_image(self.images[frame_ndx])

        # --- Apply Windowing/Leveling ---
        image_array = apply_windowing(self.current_wl, self.current_ww, image_array)

        # Rendering:
        rendered_overlay = self._render_overlays(frame_ndx)
        image_array = cv2.add(image_array, rendered_overlay)

        # Display:
        image_pil = Image.fromarray(image_array)
        image_pil_resized = image_pil.resize(self.current_size, Image.Resampling.LANCZOS)
        self.current_size = image_pil_resized.size
        self.photo_image = ImageTk.PhotoImage(image_pil_resized)
        image_pil.close()
        del image_array

        # --- Display image on Canvas ---
        # Keep a reference to the PhotoImage to prevent garbage collection
        self.canvas.image = self.photo_image  # type: ignore
        if self.canvas_image_item:
            self.canvas.delete(self.canvas_image_item)
        self.canvas_image_item = self.canvas.create_image(0, 0, anchor="nw", image=self.photo_image)

        # Caching: Store BOTH PhotoImage & resized PIL.Image
        self.add_to_cache(frame_ndx, self.photo_image, image_pil_resized)
        self.current_image_index = frame_ndx
        if self.num_images > 1:
            self.update_scrollbar()
        self.update_status()

    # Cache functions:
    def add_to_cache(self, index, photo_image, pil_image):  # Modified signature
        """Adds the PhotoImage, PIL Image and its size to the cache."""
        self.image_cache[index] = (photo_image, pil_image, self.current_size)  # Store PIL image
        if len(self.image_cache) > self.CACHE_SIZE:
            self.manage_cache()

    def remove_from_cache(self, index):
        if index not in self.image_cache:
            logger.warning(f"index: {index} not in image_cache")
            return
        # Get the PIL Image and close.
        __, pil_image, __ = self.image_cache.pop(index)
        if hasattr(pil_image, "close"):
            pil_image.close()
        gc.collect()

    def manage_cache(self):
        """Manages the cache, removing the oldest entry if it's full."""
        while len(self.image_cache) > self.CACHE_SIZE:
            oldest_key = min(self.image_cache.keys())
            self.remove_from_cache(oldest_key)

    def clear_cache(self):
        """Clears the image cache and performs garbage collection."""
        for __, (photo_image, pil_image, *__) in self.image_cache.items():
            # Explicitly break the reference held by Tkinter and PIL.Image
            if hasattr(pil_image, "close"):
                pil_image.close()  # Close the PIL.Image
            del photo_image  # Delete PhotoImage

        self.image_cache.clear()  # Clear the dictionary
        gc.collect()  # Force garbage collection

    # ImageView Event Handlers:
    def on_mousewheel(self, event):
        if event.delta > 0:
            self.change_image(self.current_image_index - 1)
        else:
            self.change_image(self.current_image_index + 1)

    def on_resize(self, event):
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()

        # Handle initial case where winfo_width/height return 1.
        if canvas_width <= 1 or canvas_height <= 1:
            return

        new_image_size = (canvas_width, canvas_height)
        if new_image_size != self.current_size:
            self.current_size = new_image_size
            self.load_and_display_image(self.current_image_index)
            self.update_status()

    def prev_image(self, event):
        self.change_image(self.current_image_index - 1)

    def next_image(self, event):
        self.change_image(self.current_image_index + 1)

    def change_image(self, new_index):
        if 0 <= new_index < self.num_images:
            self.load_and_display_image(new_index)

    def change_image_home(self, event):
        self.change_image(0)

    def change_image_end(self, event):
        self.change_image(self.num_images - 1)

    def change_image_next(self, event):
        self.change_image(self.current_image_index + self.large_jump)

    def change_image_prior(self, event):
        self.change_image(self.current_image_index - self.large_jump)

    def change_image_up(self, event):
        self.change_image(self.current_image_index + self.small_jump)

    def change_image_down(self, event):
        self.change_image(self.current_image_index - self.small_jump)

    def update_scrollbar(self):
        start = self.current_image_index / self.num_images
        end = (self.current_image_index + 1) / self.num_images
        self.scrollbar.set(start, end)

    def scroll_handler(self, *args):
        command = args[0]
        if command == "moveto":
            position = float(args[1])
            new_index = int(position * self.num_images)
            self.change_image(new_index)
        elif command == "scroll":
            value, unit = float(args[1]), args[2]
            if unit == "units":
                self.change_image(self.current_image_index + int(value))
            elif unit == "pages":
                self.change_image(self.current_image_index + int(value * self.num_images * 0.1))

    def change_fps(self, value):
        self.fps = int(value)
        self.play_delay = int(1000 / self.fps)
        self.fps_slider_label.configure(text=f"{self.fps} fps")
        if self.playing and self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = self.after(self.play_delay, self.play_loop)

    def toggle_play(self, event=None):
        self.playing = not self.playing
        if self.playing:
            self.toggle_button.configure(image=self.ctk_pause_icon)
            self.play_loop()
        else:
            self.toggle_button.configure(image=self.ctk_play_icon)
            if self.after_id:
                self.after_cancel(self.after_id)
                self.after_id = None

    def play_loop(self):
        if self.playing:
            self.next_image(None)
            self.update_status()
            if self.current_image_index == self.num_images - 1:
                self.current_image_index = 0  # Loop back to the start
            self.after_id = self.after(self.play_delay, self.play_loop)

    def _find_hit_object(self, x_view: int, y_view: int, objects: list) -> int | None:
        """
        Checks if view coordinates hit any object in the list with a get_bounding_box method.

        Args:
            x_view: The x-coordinate in view space.
            y_view: The y-coordinate in view space.
            objects: A list of objects (e.g., OCRText, Rectangle) that have
                     a get_bounding_box() method returning (x1, y1, x2, y2)
                     in *image* coordinates.

        Returns:
            Index of hit object in list otherwise None
        """
        if not objects:
            return None

        for index, obj in enumerate(objects):
            try:
                x1_img, y1_img, x2_img, y2_img = obj.get_bounding_box()
                # Convert bounding box to view coordinates for hit test
                x1_view, y1_view = self._image_to_view_coords(x1_img, y1_img)
                x2_view, y2_view = self._image_to_view_coords(x2_img, y2_img)

                if x1_view <= x_view <= x2_view and y1_view <= y_view <= y2_view:
                    return index
            except AttributeError:
                logger.warning(f"Object {obj} in list lacks get_bounding_box method.")
                continue  # Skip objects without the required method

        return None

    # Overlay editing event handlers:
    def _on_left_click(self, event):
        """
        Handles left-clicks:
        1. Checks for hits on TEXT boxes.
        2. Checks for hits on USER_RECTANGLES boxes.
        3. If no hits, initiates drawing a new user rect
           else remove hit object from corresponding overlay
        4. If current image is a projection in a series only allow user rect drawing if propagate_overlays is true
        """
        if self.playing:
            return

        x, y = int(event.x), int(event.y)  # View coordinates

        # Check Text Overlay:
        hit = False
        for i in range(self.num_images):
            if not self.propagate_overlays and i != self.current_image_index:
                continue
            if i not in self.overlay_data:
                continue
            ocr_texts_overlay_data = self.overlay_data[i].ocr_texts
            ocr_text_ndx = self._find_hit_object(x, y, ocr_texts_overlay_data)
            if ocr_text_ndx is None:
                continue
            hit = True
            if i == self.current_image_index and self.add_to_whitelist_callback:
                self.add_to_whitelist_callback(ocr_texts_overlay_data[ocr_text_ndx].text)
            del ocr_texts_overlay_data[ocr_text_ndx]

        if hit:
            logging.info(f"Remove OCR Text at {x}, {y}, propagate={self.propagate_overlays}")
            if self.propagate_overlays:
                self.clear_cache()
            self.refresh_current_image()
            return

        # Check User Rectangle Overlay:
        hit = False
        for i in range(self.num_images):
            if not self.propagate_overlays and i != self.current_image_index:
                continue
            if i not in self.overlay_data:
                continue
            user_rect_overlay_data = self.overlay_data[i].user_rects
            rect_ndx = self._find_hit_object(x, y, user_rect_overlay_data)
            if rect_ndx is None:
                continue
            hit = True
            del user_rect_overlay_data[rect_ndx]

        if hit:
            logging.info(f"Remove User Rectangle at {x}, {y}, propagate={self.propagate_overlays}")
            if self.propagate_overlays:
                self.clear_cache()
            self.refresh_current_image()
            return

        if self.num_images > 1 and not self.propagate_overlays and self.current_image_index < 3:
            logger.warning("if edit context is FRAME, User Rectangles not permitted on projection images")
            return

        # Otherwise start user drawing rectangle action:
        self.start_drawing_user_rect(event)

    def start_drawing_user_rect(self, event):
        """Starts drawing a new user definted rectangle"""
        self.drawing_rect = True
        self.start_x = int(event.x)  # Store *CANVAS (VIEW)* coordinates
        self.start_y = int(event.y)
        # Ensure any previous temporary rectangle is gone (safety check)
        if self.temp_rect_id:
            self.canvas.delete(self.temp_rect_id)
            self.temp_rect_id = None
        logger.info(f"Drawing User Rectangle start x:{self.start_x} y:{self.start_y}")
        self.canvas.config(cursor="sizing")

    def draw_box(self, event):
        """
        Updates the visual representation of the box being drawn temporarily.
        (Bound to <B3-Motion> for right-click drag)
        """
        # Only run if we are currently in the drawing state
        if not self.drawing_rect or self.start_x is None or self.start_y is None:
            return

        # Get current coordinates in CANVAS (VIEW) space
        current_x = int(event.x)
        current_y = int(event.y)

        # Delete the previous temporary rectangle item, if it exists
        if self.temp_rect_id:
            self.canvas.delete(self.temp_rect_id)

        # Create a new temporary rectangle item on the canvas
        # Use canvas coordinates directly. Choose a distinct outline color.
        self.temp_rect_id = self.canvas.create_rectangle(
            self.start_x,
            self.start_y,
            current_x,
            current_y,
            outline="cyan",  # Use a visible color like blue or cyan
            width=1,
            # Consider adding 'dash=(2, 4)' for a dashed line effect
        )

    def end_drawing_user_rect(self, event):
        """
        Finalizes drawing: removes temp rect, adds permanent rect to overlay_data,
        and triggers a full redraw of the background image item.
        (Bound to <ButtonRelease-3>)
        """
        # --- Check if drawing was valid ---
        if not self.drawing_rect:
            self.canvas.config(cursor="")
            return

        if self.start_x is None or self.start_y is None:
            logger.warning("Invalid drawing state, start coordinate invalid")
            self.canvas.config(cursor="")
            return

        # Get final coordinates before resetting state
        end_x = int(event.x)
        end_y = int(event.y)

        # --- Canvas Cleanup ---
        # Delete the final temporary rectangle item from the canvas
        if self.temp_rect_id:
            self.canvas.delete(self.temp_rect_id)
            self.temp_rect_id = None

        # Reset drawing state *after* getting coordinates but *before* processing
        self.drawing_rect = False
        local_start_x = self.start_x  # Copy start coords before clearing
        local_start_y = self.start_y
        self.start_x = None
        self.start_y = None

        # --- Create Permanent Box in Image Coordinates ---
        # Convert the start (view) and end (view) coordinates to image coordinates.
        try:
            x1_img, y1_img = self._view_to_image_coords(local_start_x, local_start_y)
            x2_img, y2_img = self._view_to_image_coords(end_x, end_y)
        except Exception as e:  # Catch potential errors during conversion
            logger.error(f"Error converting view coords to image coords: {e}")
            self.canvas.config(cursor="")
            return

        # Ensure correct ordering
        final_x1 = min(x1_img, x2_img)
        final_y1 = min(y1_img, y2_img)
        final_x2 = max(x1_img, x2_img)
        final_y2 = max(y1_img, y2_img)

        # --- Snapping Logic ---
        snap_threshold = 5  # Pixels in VIEW coordinates
        view_width, view_height = self.current_size

        # Check X coordinates against view boundaries
        if local_start_x <= snap_threshold or end_x <= snap_threshold:
            final_x1 = 0  # Snap left edge to image left edge
            logger.debug("Snapping X1 to image edge (0)")
        if local_start_x >= view_width - snap_threshold or end_x >= view_width - snap_threshold:
            final_x2 = self.image_width  # Snap right edge to image right edge
            logger.debug(f"Snapping X2 to image edge ({self.image_width})")

        # Check Y coordinates against view boundaries
        if local_start_y <= snap_threshold or end_y <= snap_threshold:
            final_y1 = 0  # Snap top edge to image top edge
            logger.debug("Snapping Y1 to image edge (0)")
        if local_start_y >= view_height - snap_threshold or end_y >= view_height - snap_threshold:
            final_y2 = self.image_height  # Snap bottom edge to image bottom edge
            logger.debug(f"Snapping Y2 to image edge ({self.image_height})")

        # --- Add to Overlay Data ---
        # Check for minimum box size
        min_width = 5
        min_height = 5
        if abs(final_x1 - final_x2) < min_width or abs(final_y1 - final_y2) < min_height:
            logger.info("ImageViewer: Drawn rect too small, not adding.")
            # Need to redraw to remove the temporary rectangle even if not adding
            self.refresh_current_image()
            self.canvas.config(cursor="")
            return

        new_user_rect = UserRectangle(
            top_left=(final_x1, final_y1),
            bottom_right=(final_x2, final_y2),
        )

        # --- Add User Rectangle to Overlay Data from SeriesView (edit context sensitive) ---
        logger.info(
            f"Add user rectangle to overlay data for current frame: {new_user_rect.top_left} -> {new_user_rect.bottom_right}, propagate: {self.propagate_overlays}"
        )
        for i in range(self.num_images):
            if not self.propagate_overlays and i != self.current_image_index:
                continue
            if i in self.overlay_data:
                self.overlay_data[i].user_rects.append(new_user_rect)
            else:
                self.overlay_data[i] = OverlayData()
                self.overlay_data[i].user_rects = [new_user_rect]

        if self.propagate_overlays:
            self.clear_cache()

        self.canvas.config(cursor="")
        self.refresh_current_image()

    # --- WW/WL (Brightness/Contrast) Calculation ---
    def _update_derived_alpha_beta(self):
        """
        Calculates the internal alpha and beta values used by cv2.convertScaleAbs
        based on the current user-facing self.current_ww and self.current_wl.
        """
        # Ensure WW is at least 1 to avoid division by zero and extreme alpha
        ww_safe = max(1.0, self.current_ww)
        self._derived_alpha = 255.0 / ww_safe
        # Calculate beta so that the pixel value 'wl' maps to the middle
        # of the output range (127.5 for 0-255)
        self._derived_beta = int(127.5 - (self._derived_alpha * self.current_wl))

    # --- WW/WL Adjustment Event Handlers ---
    def _start_adjust_display(self, event):
        """Starts WL/WW adjustment. (Bound to <ButtonPress-3>)"""
        if self.drawing_rect:
            return  # Ignore if drawing
        logger.debug("Starting WL/WW adjust")
        self.adjusting_wlww = True
        self.adjust_start_x = int(event.x)
        self.adjust_start_y = int(event.y)
        self.initial_wl = self.current_wl
        self.initial_ww = self.current_ww
        self.canvas.config(cursor="fleur")

    def _adjust_display(self, event):
        """Adjusts WL(U/D)/WW(L/R) during drag. (Bound to <B3-Motion>)"""
        if not self.adjusting_wlww or self.adjust_start_x is None or self.adjust_start_y is None:
            return

        current_x = int(event.x)
        current_y = int(event.y)
        delta_x = current_x - self.adjust_start_x
        delta_y = current_y - self.adjust_start_y  # Down = Positive Delta Y

        # --- Calculate New WW/WL based on Mouse Mapping ---
        # Adjust sensitivity based on data range? For now, use defaults.
        wl_sensitivity = self.DEFAULT_WL_SENSITIVITY
        ww_sensitivity = self.DEFAULT_WW_SENSITIVITY

        # WL (Brightness): Up/Down drag -> Up = Brighter (Higher WL)
        self.current_wl = self.initial_wl + (-delta_y / wl_sensitivity)

        # WW (Contrast): Left/Right drag -> Left = Less contrast (Higher WW)
        self.current_ww = self.initial_ww + (delta_x / ww_sensitivity)

        # Clamp WW (must be > 0)
        self.current_ww = max(1.0, self.current_ww)
        # Optional: Clamp WL based on data range if known, otherwise allow free range
        # self.current_wl = max(some_min, min(some_max, self.current_wl))

        logger.debug(f"Adjusting Display: WL={self.current_wl:.1f}, WW={self.current_ww:.1f}")

        # --- Update Histogram ---
        self.histogram.set_wlww(self.current_wl, self.current_ww)

        # --- Trigger Redraw ---
        self.refresh_current_image()

    def _end_adjust_display(self, event):
        """Ends WL/WW adjustment. (Bound to <ButtonRelease-3>)"""
        if not self.adjusting_wlww:
            return
        logger.debug("Ending WL/WW adjust")
        self.adjusting_wlww = False
        self.adjust_start_x = None
        self.adjust_start_y = None
        # Final redraw to potentially update cache with final WW/WL settings
        self.refresh_current_image()
        self.canvas.config(cursor="")

    def destroy(self):
        """Override destroy to properly clean up resources."""
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None
        self.clear_cache()  # Clear the cache before destroying the widget
        self.images = None  # type: ignore # Release the image
        super().destroy()
