import gc
import time
from tkinter import ttk

import customtkinter as ctk
import numpy as np
from PIL import Image, ImageTk


class ImageViewer(ctk.CTkFrame):
    NORMAL_FPS = 12
    FAST_FPS = 24
    PLAY_BTN_SIZE = (32, 32)
    PAD = 5

    def __init__(self, parent, num_images=1000, image_width=800, image_height=800, char_width_px=10):
        super().__init__(master=parent)  # Call the superclass constructor
        self.parent = parent
        self.num_images = num_images
        self.image_width = image_width
        self.image_height = image_height
        self.current_image_index = 0
        self.image_cache = {}  # Cache for loaded images
        self.cache_size = 50  # Maximum number of images to keep in cache.
        self.images = None  # keep images loaded for faster initial load
        self.fps = self.NORMAL_FPS  # Frames per second for playback
        self.playing = False  # Playback state
        self.play_delay = int(1000 / self.fps)  # Delay in milliseconds, initial value
        self.after_id = None  # Store the ID of the 'after' call
        self.current_size = (image_width, image_height)

        # --- Load Button Icons ---
        # Load images and convert to Pillow Image
        play_image = Image.open("src/prototyping/play.png").resize(self.PLAY_BTN_SIZE)
        pause_image = Image.open("src/prototyping/pause.png").resize(self.PLAY_BTN_SIZE)

        # Create CTkImage objects
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

        # Control Frame (Use grid inside the frame, too)
        self.control_frame = ctk.CTkFrame(self)
        self.control_frame.grid(row=2, column=0, sticky="ew", padx=self.PAD, pady=self.PAD)
        # Configure control_frame's columns
        # self.control_frame.grid_columnconfigure(0, weight=1)  # Button gets some space
        self.control_frame.grid_columnconfigure(1, weight=1)  # Status gets more

        # --- Toggle Button (Play/Pause) ---
        self.toggle_button = ctk.CTkButton(
            self.control_frame, text="", image=self.ctk_play_icon, width=self.PLAY_BTN_SIZE[0], command=self.toggle_play
        )
        self.toggle_button.grid(row=0, column=1)

        # --- Status Label (1/[images]) ---
        max_status_length = len(f"{self.num_images}/{self.num_images}")
        self.status_label = ctk.CTkLabel(
            self.control_frame,
            text=f"1/{self.num_images}",
            font=("Courier Bold", 14),  # fixed width font
            width=max_status_length * char_width_px,
        )
        self.status_label.grid(row=0, column=2, sticky="e")

        # --- Key Bindings ---
        parent.bind("<Left>", self.prev_image)
        parent.bind("<Right>", self.next_image)
        parent.bind("<Up>", lambda event: self.change_image(self.current_image_index + 10))
        parent.bind("<Down>", lambda event: self.change_image(self.current_image_index - 10))
        parent.bind("<Prior>", lambda event: self.change_image(self.current_image_index - 100))
        parent.bind("<Next>", lambda event: self.change_image(self.current_image_index + 100))
        parent.bind("<Home>", lambda event: self.change_image(0))
        parent.bind("<End>", lambda event: self.change_image(self.num_images - 1))
        parent.bind("<space>", lambda event: self.toggle_play())
        parent.bind("<MouseWheel>", self.on_mousewheel)
        parent.bind("<Configure>", self.on_resize)  # Bind to resize events

        # --- Image Generation (only on startup)---
        self.generate_test_images()
        self.load_and_display_image(0)

        self.focus_set()

    def generate_test_images(self):
        print("Generating test images...")
        start_time = time.time()
        self.images = np.random.randint(
            0, 256, size=(self.num_images, self.image_height, self.image_width, 3), dtype=np.uint8
        )
        end_time = time.time()
        print(f"Image generation took {end_time - start_time:.2f} seconds")

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
                self.status_label.configure(text=f"{self.current_image_index + 1}/{self.num_images}")
                return

        image_array = self.images[index]
        image = Image.fromarray(image_array)
        image = image.resize(self.current_size, Image.Resampling.LANCZOS)
        photo_image = ImageTk.PhotoImage(image)
        self.add_to_cache(index, photo_image)

        self.image_label.configure(image=photo_image)
        self.image_label.image = photo_image  # type: ignore # Keep a reference, crucially important for Tkinter.
        self.current_image_index = index
        self.update_scrollbar()
        self.status_label.configure(text=f"{self.current_image_index + 1}/{self.num_images}")

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

    def prev_image(self, event):
        self.change_image(self.current_image_index - 1)

    def next_image(self, event):
        self.change_image(self.current_image_index + 1)

    def change_image(self, new_index):
        if 0 <= new_index < self.num_images:
            self.load_and_display_image(new_index)

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
                self.toggle_play()
                return
            self.after_id = self.after(self.play_delay, self.play_loop)


def main():
    ctk.set_appearance_mode("System")  # Follow system appearance
    ctk.set_default_color_theme("blue")

    root = ctk.CTk()
    root.title("Image Viewer")
    root.geometry("800x850")  # Increased height for controls

    viewer = ImageViewer(root, num_images=1000, image_width=800, image_height=800)
    viewer.pack(fill=ctk.BOTH, expand=True)  # Fill available space

    root.mainloop()


if __name__ == "__main__":
    main()
