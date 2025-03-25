import gc
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
import tkinter as tk
from tkinter import ttk
from typing import Callable

import customtkinter as ctk
import cv2
import numpy as np
from PIL import Image, ImageTk

from anonymizer.controller.remove_pixel_phi import OCRText
from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)


# Overlay layer types:
class LayerType(Enum):
    TEXT = auto()  # text and rectangle coordinates
    SEGMENTATIONS = auto()  # polygon vertices
    # ... other layer types ...


@dataclass
class PolygonPoint:
    x: int
    y: int


@dataclass
class Segmentation:
    points: list[PolygonPoint]


@dataclass
class OverlayData:
    """Holds all overlay data for a single frame."""

    text: list[OCRText] = field(default_factory=list)  # List of text boxes
    segmentations: list[Segmentation] = field(default_factory=list)  # List of segmentations
    # Add other overlay types here as needed, using Union if necessary.


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

    def __init__(self, parent, images: np.ndarray, add_to_whitelist_callback: Callable[[str], None] | None = None):
        super().__init__(master=parent)  # Call the superclass constructor
        self.parent = parent
        self.num_images: int = images.shape[0]
        self.images: np.ndarray = images
        self.add_to_whitelist_callback = add_to_whitelist_callback
        self.image_width: int = images.shape[2]
        self.image_height: int = images.shape[1]
        self.current_image_index: int = 0
        # Cache for loaded images: cache index: (PhotoImage, (Width, Height))
        self.image_cache: dict[int, tuple[ImageTk.PhotoImage, Image.Image, tuple[int, int]]] = {}
        self.fps: int = self.NORMAL_FPS  # Frames per second for playback
        self.playing: bool = False  # Playback state
        self.play_delay: int = int(1000 / self.fps)  # Delay in milliseconds, initial value
        self.after_id = None  # Store the ID of the 'after' call
        self.current_size: tuple[int, int] = (images.shape[2], images.shape[1])
        self.overlay_data: dict[int, OverlayData] = {}  # Store overlay data per frame
        self.active_layers: set[LayerType] = set()
        self.active_layers.add(LayerType.TEXT)
        self.temp_rect_id = None
        self.drawing_box = False
        self.start_x = None
        self.start_y = None

        # --- Calculate Jump Amounts Dynamically ---
        self.small_jump: int = max(1, int(self.num_images * self.SMALL_JUMP_PERCENTAGE))  # Ensure at least 1
        self.large_jump: int = max(1, int(self.num_images * self.LARGE_JUMP_PERCENTAGE))

        # --- Load Button Icons ---
        # Load images and convert to Pillow Image
        play_image = Image.open("assets/icons/play.png").resize(self.PLAY_BTN_SIZE)
        pause_image = Image.open("assets/icons/pause.png").resize(self.PLAY_BTN_SIZE)

        # --- Create CTkImage objects ---
        self.ctk_play_icon = ctk.CTkImage(light_image=play_image, dark_image=play_image, size=self.PLAY_BTN_SIZE)
        self.ctk_pause_icon = ctk.CTkImage(light_image=pause_image, dark_image=pause_image, size=self.PLAY_BTN_SIZE)

        # --- UI Elements ---
        # --- Grid Layout ---
        self.grid_rowconfigure(0, weight=1)  # Image label row expands
        self.grid_columnconfigure(0, weight=1)  # Image label column expands

        # Image Label (holds current frame pixels)
        # self.image_label = ctk.CTkLabel(self, text="")
        # self.image_label.grid(row=0, column=0, sticky="nsew")  # Fill entire cell
        self.canvas = tk.Canvas(self, bg="black", borderwidth=0, highlightthickness=0)  # Use appropriate background
        self.canvas_image_item = None  # Add this attribute to store the ID of the image on the canvas
        self.canvas.grid(row=0, column=0, sticky="nsew")

        # Scrollbar
        self.scrollbar = ttk.Scrollbar(self, orient=ctk.HORIZONTAL, command=self.scroll_handler)
        self.scrollbar.grid(row=1, column=0, sticky="ew")  # sticky="ew"
        self.update_scrollbar()

        # Control Frame for fixed width widgets
        self.control_frame = ctk.CTkFrame(self)
        self.control_frame.grid(row=2, column=0, padx=self.PAD, pady=self.PAD, sticky="ew")
        self.control_frame.grid_columnconfigure(1, weight=1)

        self.image_size_label = ctk.CTkLabel(self.control_frame, text="")
        self.image_size_label.grid(row=0, column=0, sticky="w", padx=self.PAD)

        self.projection_label = ctk.CTkLabel(self.control_frame, text="")
        self.projection_label.grid(row=1, column=0, sticky="w", padx=self.PAD)

        # --- Toggle Button (Play/Pause) for mulit-frame series ---
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
        self.image_number_label.grid(row=1, column=3, sticky="e", padx=(0, self.PAD))

        # Event binding:
        # Mouse:
        self.bind("<Configure>", self.on_resize)
        self.bind("<MouseWheel>", self.on_mousewheel)
        # self.image_label.bind("<MouseWheel>", self.on_mousewheel)
        # self.image_label.bind("<Button-1>", self._on_left_click)
        # self.image_label.bind("<B3-Motion>", self.draw_box)  # Right-click drag
        # self.image_label.bind("<ButtonRelease-3>", self.end_drawing_box)  # Right-click release
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<Button-1>", self._on_left_click)
        self.canvas.bind("<B1-Motion>", self.draw_box)  # left-click drag
        self.canvas.bind("<ButtonRelease-1>", self.end_drawing_box)  # left-click release

        self.control_frame.bind("<MouseWheel>", self.on_mousewheel)
        # Keys:
        # Note: customtkinter key bindings bind to the canvas of the frame
        # see here: https://stackoverflow.com/questions/77676235/tkinter-focus-set-on-frame
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
        # TODO: understand why customtkinter doesn't do this correctly
        self.bind("<Enter>", self.mouse_enter)
        # self.image_label.bind("<Enter>", self.mouse_enter)
        self.canvas.bind("<Enter>", self.mouse_enter)
        self.control_frame.bind("<Enter>", self.mouse_enter)
        self.bind("<FocusIn>", self.on_focus_in)
        self.bind("<FocusOut>", self.on_focus_out)
        # self.image_label.bind("<FocusIn>", self.on_focus_in)
        self.canvas.bind("<FocusIn>", self.on_focus_in)

        self.after_idle(self._set_initial_size)
        self.update_status()

    def get_current_image(self) -> np.ndarray:
        return self.images[self.current_image_index]

    def set_text_overlay_data(self, frame_index: int, data: list[OCRText]):
        if frame_index not in self.overlay_data:
            self.overlay_data[frame_index] = OverlayData()
        self.overlay_data[frame_index].text = data
        if frame_index == self.current_image_index:  # update display
            self.remove_from_cache(frame_index)  # force re-rendering
            self.load_and_display_image(self.current_image_index)

    def set_segmentation_overlay_data(self, frame_index: int, data: list[Segmentation]):
        if frame_index not in self.overlay_data:
            self.overlay_data[frame_index] = OverlayData()
        self.overlay_data[frame_index].segmentations = data
        if frame_index == self.current_image_index:
            self.load_and_display_image(self.current_image_index)

    def get_text_overlay_data(self, frame_index: int) -> list[OCRText] | None:
        """Retrieves the text overlay data for a specific frame."""
        if frame_index not in self.overlay_data:
            return None
        return self.overlay_data[frame_index].text

    def get_segmentation_overlay_data(self, frame_index: int) -> list[Segmentation] | None:
        """Retrieves the segmentation overlay data for a specific frame."""
        if frame_index not in self.overlay_data:
            return None
        return self.overlay_data[frame_index].segmentations

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
        del self.image_cache[self.current_image_index]
        self.load_and_display_image(self.current_image_index)

    def mouse_enter(self, event):
        logger.debug("mouse_enter")
        self._canvas.focus_set()

    def on_focus_in(self, event):
        logger.debug("ImageViewer has focus")

    def on_focus_out(self, event):
        logger.debug("ImageViewer lost focus")

    def _set_initial_size(self):
        """Calculates and sets the initial image size based on screen size."""
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        max_width = int(screen_width * self.MAX_SCREEN_PERCENTAGE)
        max_height = int(screen_height * self.MAX_SCREEN_PERCENTAGE)

        self.current_size = self._calculate_scaled_size(max_width, max_height)
        self.canvas.config(width=self.current_size[0], height=self.current_size[1])
        self.load_and_display_image(0)
        self._canvas.focus_set()

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

    def _render_overlays(self) -> np.ndarray:
        """Renders all active overlays for current frame."""

        combined_overlay = np.zeros((self.image_height, self.image_width, 3), dtype=np.uint8)
        if self.current_image_index not in self.overlay_data:
            return combined_overlay

        current_frame_data = self.overlay_data[self.current_image_index]

        for layer_name in self.active_layers:
            if layer_name == LayerType.TEXT and current_frame_data.text:
                for text_data in current_frame_data.text:
                    x1, y1, x2, y2 = text_data.get_bounding_box()
                    cv2.rectangle(combined_overlay, (x1, y1), (x2, y2), self.TEXT_BOX_COLOR, 2)

            elif layer_name == LayerType.SEGMENTATIONS and current_frame_data.segmentations:
                # TODO: segment annotation creation and display
                for segmentation in current_frame_data.segmentations:
                    points = np.array([(p.x, p.y) for p in segmentation.points], dtype=np.int32)
                    cv2.fillPoly(combined_overlay, [points], (255, 0, 0))  # Filled red

        return combined_overlay

    def load_and_display_image(self, index: int):
        if not (0 <= index < self.num_images) or self.images is None:
            return

        # Use Cache:
        if index in self.image_cache:
            cached_image, __, cached_size = self.image_cache[index]
            if cached_size == self.current_size:
                self.photo_image = cached_image
                # self.image_label.configure(image=self.photo_image)
                # self.image_label.image = self.photo_image  # type: ignore # Keep a reference, crucially important for Tkinter.
                self.canvas.image = self.photo_image  # type: ignore
                if self.canvas_image_item:
                    self.canvas.delete(self.canvas_image_item)
                self.canvas_image_item = self.canvas.create_image(0, 0, anchor="nw", image=self.photo_image)
                self.current_image_index = index
                self.update_scrollbar()
                self.update_status()
                return

        image_array = self.images[index].copy()
        if len(image_array.shape) == 2:  # TODO: necessary?
            image_array = cv2.cvtColor(image_array, cv2.COLOR_GRAY2BGR)

        # Rendering:
        rendered_overlay = self._render_overlays()
        image_array = cv2.add(image_array, rendered_overlay)

        # Display:
        image_pil = Image.fromarray(image_array)
        image_pil_resized = image_pil.resize(self.current_size, Image.Resampling.LANCZOS)
        self.current_size = image_pil_resized.size
        self.photo_image = ImageTk.PhotoImage(image_pil_resized)
        image_pil.close()
        del image_array

        # self.image_label.configure(image=self.photo_image)
        # self.image_label.image = self.photo_image  # type: ignore # Keep a reference, crucially important for Tkinter.
        # --- Display image on Canvas ---
        # Keep a reference to the PhotoImage to prevent garbage collection
        self.canvas.image = self.photo_image  # type: ignore
        if self.canvas_image_item:
            self.canvas.delete(self.canvas_image_item)
        self.canvas_image_item = self.canvas.create_image(0, 0, anchor="nw", image=self.photo_image)

        # Optional: Update canvas size if necessary (though typically done by layout)
        # self.canvas.config(width=self.current_size[0], height=self.current_size[1])

        # Caching: Store BOTH PhotoImage & resized PIL.Image
        self.add_to_cache(index, self.photo_image, image_pil_resized)
        self.current_image_index = index
        self.update_scrollbar()
        self.update_status()

    # Cache functions:
    def add_to_cache(self, index, photo_image, pil_image):  # Modified signature
        """Adds the PhotoImage, PIL Image and its size to the cache."""
        self.image_cache[index] = (photo_image, pil_image, self.current_size)  # Store PIL image
        if len(self.image_cache) > self.CACHE_SIZE:
            self.manage_cache()

    def remove_from_cache(self, index):
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
        for _, (photo_image, pil_image, *__) in self.image_cache.items():
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
        # label_width = self.image_label.winfo_width()
        # label_height = self.image_label.winfo_height()
        label_width = self.canvas.winfo_width()
        label_height = self.canvas.winfo_height()

        # Handle initial case where winfo_width/height return 1.
        if label_width <= 1 or label_height <= 1:
            return

        new_image_size = (label_width, label_height)
        if new_image_size != self.current_size:
            self.current_size = new_image_size
            self.load_and_display_image(self.current_image_index)

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
            if self.current_image_index == self.num_images - 1:
                self.current_image_index = 0  # Loop back to the start
            self.after_id = self.after(self.play_delay, self.play_loop)

    # Overlay editing event handlers:
    def _on_left_click(self, event):
        """Handles left-clicks on the image, checking for text box hits."""
        current_index = self.current_image_index
        text_overlay_data = self.get_text_overlay_data(current_index)

        if not text_overlay_data:
            return

        x, y = int(event.x), int(event.y)  # View coordinates

        for i, ocr_text in enumerate(text_overlay_data):
            x1, y1, x2, y2 = ocr_text.get_bounding_box()
            # Convert bounding box to view coordinates
            x1_view, y1_view = self._image_to_view_coords(x1, y1)
            x2_view, y2_view = self._image_to_view_coords(x2, y2)

            if x1_view <= x <= x2_view and y1_view <= y <= y2_view:
                logging.info(f"Left-click inside text box Removing {ocr_text.text}")
                del text_overlay_data[i]
                self.set_text_overlay_data(current_index, text_overlay_data)
                if self.add_to_whitelist_callback:
                    self.add_to_whitelist_callback(ocr_text.text)
                return

        self.start_drawing_box(event)

    def start_drawing_box(self, event):
        """Starts drawing a new text box."""
        self.drawing_box = True
        self.start_x = int(event.x)  # Store *CANVAS (VIEW)* coordinates
        self.start_y = int(event.y)
        # Ensure any previous temporary rectangle is gone (safety check)
        if self.temp_rect_id:
            self.canvas.delete(self.temp_rect_id)
            self.temp_rect_id = None
        logger.info(f"Drawing box start x:{self.start_x} y:{self.start_y}")

    def draw_box(self, event):
        """
        Updates the visual representation of the box being drawn temporarily.
        (Bound to <B3-Motion> for right-click drag)
        """
        # Only run if we are currently in the drawing state
        if not self.drawing_box or self.start_x is None or self.start_y is None:
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

    def end_drawing_box(self, event):
        """
        Finalizes drawing: removes temp rect, adds permanent rect to overlay_data,
        and triggers a full redraw of the background image item.
        (Bound to <ButtonRelease-3>)
        """
        # Get final coordinates before resetting state
        end_x = int(event.x)
        end_y = int(event.y)

        # --- Canvas Cleanup ---
        # Delete the final temporary rectangle item from the canvas
        if self.temp_rect_id:
            self.canvas.delete(self.temp_rect_id)
            self.temp_rect_id = None

        # --- Check if drawing was valid ---
        if not self.drawing_box or self.start_x is None or self.start_y is None:
            logger.warning("end_drawing_box: Invalid drawing state.")
            return  # Exit if drawing didn't start properly

        # Reset drawing state *after* getting coordinates but *before* processing
        self.drawing_box = False
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
            return

        # Ensure correct ordering
        final_x1 = min(x1_img, x2_img)
        final_y1 = min(y1_img, y2_img)
        final_x2 = max(x1_img, x2_img)
        final_y2 = max(y1_img, y2_img)

        # --- Add to Overlay Data ---
        # Optional: Check for minimum box size
        min_width = 5
        min_height = 5
        if abs(final_x1 - final_x2) < min_width or abs(final_y1 - final_y2) < min_height:
            logger.info(f"ImageViewer: Drawn box too small, not adding.")
            # Need to redraw to remove the temporary rectangle even if not adding
            self.refresh_current_image()
            return

        new_user_box = OCRText(
            text="",
            top_left=(final_x1, final_y1),
            bottom_right=(final_x2, final_y2),
            prob=0.0,  # Mark as user-drawn
        )

        # --- Add to Overlay Data ---
        ndx = self.current_image_index
        if ndx in self.overlay_data:
            ocr_list = self.overlay_data[ndx].text
            ocr_list.append(new_user_box)
        else:
            ocr_list = [new_user_box]

        self.set_text_overlay_data(self.current_image_index, ocr_list)
        logger.info(
            f"Added user text box to overlay data for current frame: {new_user_box.top_left} -> {new_user_box.bottom_right}"
        )

    def destroy(self):
        """Override destroy to properly clean up resources."""
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None
        self.clear_cache()  # Clear the cache before destroying the widget
        self.images = None  # type: ignore # Release the image
        super().destroy()
