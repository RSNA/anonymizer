import gc
import logging
from tkinter import ttk

import customtkinter as ctk
import numpy as np
from PIL import Image, ImageTk

logger = logging.getLogger(__name__)


class ImageViewer(ctk.CTkFrame):
    MIN_FPS = 1
    NORMAL_FPS = 5
    MAX_FPS = 10
    PLAY_BTN_SIZE = (32, 32)
    PAD = 10
    BUTTON_WIDTH = 100
    SMALL_JUMP_PERCENTAGE = 0.01  # 1% of the total images
    LARGE_JUMP_PERCENTAGE = 0.10  # 10% of the total images

    def __init__(self, parent, images: np.ndarray, char_width_px=10):
        super().__init__(master=parent)  # Call the superclass constructor
        self.parent = parent
        self.num_images = images.shape[0]
        self.images = images
        self.image_width = images.shape[2]  # image_width
        self.image_height = images.shape[1]  # image_height
        self.current_image_index = 0
        self.image_cache = {}  # Cache for loaded images
        self.cache_size = 50  # Maximum number of images to keep in cache.
        self.fps = self.NORMAL_FPS  # Frames per second for playback
        self.playing = False  # Playback state
        self.play_delay = int(1000 / self.fps)  # Delay in milliseconds, initial value
        self.after_id = None  # Store the ID of the 'after' call
        self.current_size = (images.shape[2], images.shape[1])

        # --- Calculate Jump Amounts Dynamically ---
        self.small_jump = max(1, int(self.num_images * self.SMALL_JUMP_PERCENTAGE))  # Ensure at least 1
        self.large_jump = max(1, int(self.num_images * self.LARGE_JUMP_PERCENTAGE))

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

        # Image Label
        self.image_label = ctk.CTkLabel(self, text="")
        self.image_label.grid(row=0, column=0, sticky="nsew")  # Fill entire cell

        # Scrollbar
        self.scrollbar = ttk.Scrollbar(self, orient=ctk.HORIZONTAL, command=self.scroll_handler)
        self.scrollbar.grid(row=1, column=0, sticky="ew")  # sticky="ew"
        self.update_scrollbar()

        # Control Frame for fixed width widgets
        self.control_frame = ctk.CTkFrame(self)
        self.control_frame.grid(row=2, column=0, sticky="ew", padx=self.PAD, pady=self.PAD)
        self.control_frame.grid_columnconfigure(1, weight=1)  # Play/Pause button - expands

        self.detect_button = ctk.CTkButton(
            self.control_frame, width=self.BUTTON_WIDTH, text="Detect Text", command=self.detect_text
        )
        self.detect_button.grid(row=0, column=0, padx=self.PAD, pady=self.PAD)
        self.detect_button = ctk.CTkButton(
            self.control_frame, width=self.BUTTON_WIDTH, text="Remove Text", command=self.remove_text
        )
        self.detect_button.grid(row=0, column=1, padx=self.PAD, pady=self.PAD, sticky="w")

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
            self.fps_slider.grid(row=0, column=2, padx=self.PAD, pady=self.PAD, sticky="e")
            self.fps_slider_label = ctk.CTkLabel(self.control_frame, text=f"{self.fps} fps")
            self.fps_slider_label.grid(row=0, column=3, pady=self.PAD, sticky="e")

            self.toggle_button = ctk.CTkButton(
                self.control_frame,
                text="",
                image=self.ctk_play_icon,
                width=self.PLAY_BTN_SIZE[0],
                command=self.toggle_play,
            )
            self.toggle_button.grid(row=0, column=4, padx=self.PAD, pady=self.PAD, sticky="e")

        # --- Status Frame (for labels) ---
        self.status_frame = ctk.CTkFrame(self)
        self.status_frame.grid(row=3, column=0, sticky="ew", padx=self.PAD, pady=(0, self.PAD))  # pady top = 0
        self.status_frame.grid_columnconfigure(0, weight=1)  # Projection label - expands, underneath play button
        self.status_frame.grid_columnconfigure(1, weight=1)  # Image number label - expands

        self.projection_label = ctk.CTkLabel(self.status_frame, text="")
        self.projection_label.grid(row=0, column=0, sticky="e", padx=self.PAD)

        self.image_size_label = ctk.CTkLabel(self.status_frame, text="")
        self.image_size_label.grid(row=0, column=1, sticky="e", padx=self.PAD)

        self.image_number_label = ctk.CTkLabel(self.status_frame, text="", font=("Courier Bold", 14))
        self.image_number_label.grid(row=0, column=2, sticky="e", padx=(0, self.PAD))

        self.bind("<Configure>", self.on_resize)  # Bind to resize events
        # # Add click-to-focus for image label, self frame & control frame:
        # self.image_label.bind("<Button-1>", self.request_focus)
        # self.control_frame.bind("<Button-1>", self.request_focus)
        # self.bind("<Button-1>", self.request_focus)

        self.load_and_display_image(0)

    def request_focus(self, event=None):
        self.focus_set()  # Set focus to this widget (ImageViewer)
        if self.parent and hasattr(self.parent, "set_focus_widget"):
            self.parent.set_focus_widget("image_viewer")

    def update_status(self):
        self.projection_label.configure(text=self.get_projection_label())
        if self.images is not None:
            image_shape = self.images[self.current_image_index].shape
            self.image_size_label.configure(text=f"[{image_shape[1]}x{image_shape[0]}]")
        self.image_number_label.configure(text=f"{self.current_image_index + 1}/{self.num_images}")

    def get_projection_label(self) -> str:
        if self.num_images == 1:
            return ""
        match self.current_image_index:
            case 0:
                return "MIN PROJECTION"
            case 1:
                return "MEAN PROJECTION"
            case 2:
                return "MAX PROJECTION"
            case _:  # Default case (for any other index)
                return ""

    def load_and_display_image(self, index):
        if not (0 <= index < self.num_images) or self.images is None:
            return

        # Use cache:
        if index in self.image_cache:
            cached_image, cached_size = self.image_cache[index]
            if cached_size == self.current_size:
                photo_image = cached_image
                self.image_label.configure(image=photo_image)
                self.image_label.image = photo_image  # type: ignore # Keep a reference, crucially important for Tkinter.
                self.current_image_index = index
                self.update_scrollbar()
                self.update_status()
                return

        image_array = self.images[index]
        image = Image.fromarray(image_array)
        image = image.resize(self.current_size, Image.Resampling.NEAREST)
        photo_image = ImageTk.PhotoImage(image)
        self.add_to_cache(index, photo_image)

        self.image_label.configure(image=photo_image)
        self.image_label.image = photo_image  # type: ignore # Keep a reference, crucially important for Tkinter.
        self.current_image_index = index
        self.update_scrollbar()
        self.update_status()

    def on_resize(self, event):
        label_width = self.image_label.winfo_width()
        label_height = self.image_label.winfo_height()

        # Handle initial case where winfo_width/height return 1.
        if label_width <= 1 or label_height <= 1:
            return

        aspect_ratio = self.image_width / self.image_height

        if label_width / label_height > aspect_ratio:  # Label is wider
            new_height = label_height
            new_width = int(new_height * aspect_ratio)
        else:  # Label is taller or same aspect ratio
            new_width = label_width
            new_height = int(new_width / aspect_ratio)

        new_image_size = (new_width, new_height)
        if new_image_size != self.current_size:
            self.current_size = new_image_size
            self.load_and_display_image(self.current_image_index)

    def add_to_cache(self, index, photo_image):
        self.image_cache[index] = (photo_image, self.current_size)
        if len(self.image_cache) > self.cache_size:
            self.manage_cache()

    def manage_cache(self):
        sorted_keys = sorted(self.image_cache.keys(), key=lambda k: abs(k - self.current_image_index), reverse=True)
        while len(self.image_cache) > self.cache_size:
            del self.image_cache[sorted_keys.pop(0)]
        gc.collect()

    def clear_cache(self):
        for _, (photo_image, _) in self.image_cache.items():
            # Explicitly break the reference held by Tkinter
            if hasattr(photo_image, "close"):  # PIL images
                photo_image.close()
            del photo_image  # Force deletion of the PhotoImage object

        self.image_cache.clear()  # Clear the dictionary
        gc.collect()

    def prev_image(self, event):
        self.change_image(self.current_image_index - 1)

    def next_image(self, event):
        self.change_image(self.current_image_index + 1)

    def change_image(self, new_index):
        if 0 <= new_index < self.num_images:
            self.load_and_display_image(new_index)

    def change_image_home(self):
        self.change_image(0)

    def change_image_end(self):
        self.change_image(self.num_images - 1)

    def change_image_next(self):
        self.change_image(self.current_image_index + self.large_jump)

    def change_image_prior(self):
        self.change_image(self.current_image_index - self.large_jump)

    def change_image_up(self):
        self.change_image(self.current_image_index + self.small_jump)

    def change_image_down(self):
        self.change_image(self.current_image_index - self.small_jump)

    def on_mousewheel(self, event):
        if event.delta > 0:
            self.change_image(self.current_image_index - 1)
        else:
            self.change_image(self.current_image_index + 1)

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

    def toggle_play(self):
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

    def detect_text(self):
        logger.info("Detecting text...")
        pass

    def remove_text(self):
        logger.info("Remove text...")
        pass

    def destroy(self):
        """Override destroy to properly clean up resources."""
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None
        self.clear_cache()  # Clear the cache before destroying the widget
        self.images = None  # Release the image
        super().destroy()
