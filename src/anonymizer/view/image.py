import gc
import logging
from tkinter import ttk

import customtkinter as ctk
import numpy as np
from PIL import Image, ImageTk

from anonymizer.utils.translate import _

logger = logging.getLogger(__name__)


class ImageViewer(ctk.CTkFrame):
    CACHE_SIZE = 50  # Maximum number of images to keep in cache
    MIN_FPS = 1
    NORMAL_FPS = 5
    MAX_FPS = 10
    PRELOAD_FRAMES = 10  # Number of frames to preload
    PLAY_BTN_SIZE = (32, 32)
    BUTTON_WIDTH = 100
    PAD = 10
    SMALL_JUMP_PERCENTAGE = 0.01  # 1% of the total images
    LARGE_JUMP_PERCENTAGE = 0.10  # 10% of the total images
    MAX_SCREEN_PERCENTAGE = 0.7  # area of current screen available for displaying image

    def __init__(self, parent, images: np.ndarray, char_width_px=10):
        super().__init__(master=parent)  # Call the superclass constructor
        self.parent = parent
        self.num_images: int = images.shape[0]
        self.images: np.ndarray = images
        self.image_width: int = images.shape[2]
        self.image_height: int = images.shape[1]
        self.current_image_index: int = 0
        self.image_cache = {}  # Cache for loaded images
        self.fps: int = self.NORMAL_FPS  # Frames per second for playback
        self.playing: bool = False  # Playback state
        self.play_delay: int = int(1000 / self.fps)  # Delay in milliseconds, initial value
        self.after_id = None  # Store the ID of the 'after' call
        self.current_size: tuple[int, int] = (images.shape[2], images.shape[1])
        self._ocr_reader = None

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
        self.image_label = ctk.CTkLabel(self, text="")
        self.image_label.grid(row=0, column=0, sticky="nsew")  # Fill entire cell

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
        self.bind("<Configure>", self.on_resize)
        self.image_label.bind("<MouseWheel>", self.on_mousewheel)
        self.bind("<MouseWheel>", self.on_mousewheel)
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
        self.image_label.bind("<Enter>", self.mouse_enter)
        # self.status_frame.bind("<Enter>", self.mouse_enter)
        self.control_frame.bind("<Enter>", self.mouse_enter)
        self.bind("<FocusIn>", self.on_focus_in)
        self.bind("<FocusOut>", self.on_focus_out)
        self.image_label.bind("<FocusIn>", self.on_focus_in)

        self.after_idle(self._set_initial_size)
        self.update_status()

    def get_current_image(self) -> np.ndarray:
        return self.images[self.current_image_index]

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
        """Calculates and sets the initial image size based on active screen size, preserving aspect ratio."""
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        max_width = int(screen_width * self.MAX_SCREEN_PERCENTAGE)
        max_height = int(screen_height * self.MAX_SCREEN_PERCENTAGE)
        aspect_ratio = self.image_width / self.image_height

        if self.image_width > max_width or self.image_height > max_height:
            if self.image_width / max_width > self.image_height / max_height:
                new_width = max_width
                new_height = int(new_width / aspect_ratio)
            else:
                new_height = max_height
                new_width = int(new_height * aspect_ratio)
            self.current_size = (new_width, new_height)
        else:
            self.current_size = (self.image_width, self.image_height)
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
        image = image.resize(self.current_size, Image.Resampling.LANCZOS)
        self.current_size = image.size
        photo_image = ImageTk.PhotoImage(image)
        self.add_to_cache(index, photo_image)

        self.image_label.configure(image=photo_image)
        self.image_label.image = photo_image  # type: ignore # Keep a reference, crucially important for Tkinter.
        self.current_image_index = index
        self.update_scrollbar()
        self.update_status()

    # Cache functions:
    def add_to_cache(self, index, photo_image):
        self.image_cache[index] = (photo_image, self.current_size)
        if len(self.image_cache) > self.CACHE_SIZE:
            self.manage_cache()

    def manage_cache(self):
        while len(self.image_cache) > self.CACHE_SIZE:
            oldest_key = min(self.image_cache.keys())
            del self.image_cache[oldest_key]
        gc.collect()

    def clear_cache(self):
        for _, (photo_image, _) in self.image_cache.items():
            # Explicitly break the reference held by Tkinter
            if hasattr(photo_image, "close"):  # PIL images
                photo_image.close()
            del photo_image  # Force deletion of the PhotoImage object

        self.image_cache.clear()  # Clear the dictionary
        gc.collect()

    # ImageView Event Handlers:
    def on_mousewheel(self, event):
        if event.delta > 0:
            self.change_image(self.current_image_index - 1)
        else:
            self.change_image(self.current_image_index + 1)

    def on_resize(self, event):
        label_width = self.image_label.winfo_width()
        label_height = self.image_label.winfo_height()

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

    def destroy(self):
        """Override destroy to properly clean up resources."""
        if self.after_id:
            self.after_cancel(self.after_id)
            self.after_id = None
        self.clear_cache()  # Clear the cache before destroying the widget
        self.images = None  # type: ignore # Release the image
        if self._ocr_reader:
            # Attempt to unload the model
            del self._ocr_reader
            self._ocr_reader = None
            gc.collect()
        super().destroy()
