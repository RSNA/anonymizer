import gc  # Garbage collection
import time
import tkinter as tk
from tkinter import ttk

import numpy as np
from PIL import Image, ImageTk  # Use Pillow for efficient image handling


class ImageViewer:
    NORMAL_FPS = 12
    FAST_FPS = 24
    PLAY_BTN_SIZE = (32, 32)

    def __init__(self, master, num_images=1000, image_width=800, image_height=800):
        self.master = master
        master.title("Image Stack Viewer")
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
        self.status_label = None  # For overlaying status

        # --- Load Icons (using Pillow) ---
        self.play_icon = ImageTk.PhotoImage(Image.open("src/prototyping/play.png").resize(self.PLAY_BTN_SIZE))
        self.pause_icon = ImageTk.PhotoImage(Image.open("src/prototyping/pause.png").resize(self.PLAY_BTN_SIZE))

        # --- UI Elements ---
        # Use a Frame to hold both image_label and allow status overlay.
        self.image_frame = tk.Frame(master)
        self.image_frame.pack(side=tk.TOP)

        self.image_label = tk.Label(self.image_frame)  # add to frame
        self.image_label.pack()

        # Scrollbar (packed second, directly below image)
        self.scrollbar = ttk.Scrollbar(master, orient=tk.HORIZONTAL, command=self.scroll_handler)
        self.scrollbar.pack(fill=tk.X)  # fill all horizontal space
        self.update_scrollbar()

        # --- Control Frame (for button and status) ---
        self.control_frame = tk.Frame(master)
        self.control_frame.pack(side=tk.TOP, pady=5)  # , fill=tk.X)  # Fill horizontally

        # --- Toggle Button (Play/Pause) ---
        self.toggle_button = tk.Button(self.control_frame, image=self.play_icon, command=self.toggle_play)
        self.toggle_button.pack(padx=2)  # Pack *inside* control_frame

        self.status_label = tk.Label(
            self.control_frame,
            text=f"1/{self.num_images}",
            width=15,
            # anchor="e",
        )
        self.status_label.pack(padx=5)

        # --- Key Bindings ---
        master.bind("<Left>", self.prev_image)
        master.bind("<Right>", self.next_image)
        master.bind("<Up>", lambda event: self.change_image(self.current_image_index + 10))
        master.bind("<Down>", lambda event: self.change_image(self.current_image_index - 10))
        master.bind("<Prior>", lambda event: self.change_image(self.current_image_index - 100))  # page up
        master.bind("<Next>", lambda event: self.change_image(self.current_image_index + 100))  # page down
        master.bind("<Home>", lambda event: self.change_image(0))
        master.bind("<End>", lambda event: self.change_image(self.num_images - 1))
        master.bind("<space>", lambda event: self.toggle_play())  # Bind spacebar to toggle_play

        # bind mouse wheel
        master.bind("<MouseWheel>", self.on_mousewheel)

        # --- Image Generation (only on startup)---
        self.generate_test_images()
        self.load_and_display_image(0)  # Load and display the first image

    def generate_test_images(self):
        """Generates a stack of test images efficiently."""
        print("Generating test images...")
        start_time = time.time()

        self.images = np.random.randint(
            0, 256, size=(self.num_images, self.image_height, self.image_width, 3), dtype=np.uint8
        )

        end_time = time.time()
        print(f"Image generation took {end_time - start_time:.2f} seconds")

    def create_status_label(self):
        """Creates status label."""
        return tk.Label(self.image_frame, text="", font=("Courier", 10, "bold"), bg="black", fg="white")

    def load_and_display_image(self, index):
        """Loads an image (from cache or generates), converts to PhotoImage, and displays."""
        if not (0 <= index < self.num_images) or self.images is None:
            return

        if index in self.image_cache:
            # print(f"Loading image {index} from cache")
            photo_image = self.image_cache[index]  # Get from cache
        else:
            # print(f"Loading image {index} from array")
            image_array = self.images[index]  # Get pregenerated numpy array
            image = Image.fromarray(image_array)
            photo_image = ImageTk.PhotoImage(image)
            self.add_to_cache(index, photo_image)  # Add to cache

        self.image_label.configure(image=photo_image)
        self.image_label.image = photo_image  # type: ignore # Keep a reference, crucially important for Tkinter.
        self.current_image_index = index
        self.update_scrollbar()  # Update scrollbar position

        # --- Overlay Status Label ---
        self.update_status_label()

    def update_status_label(self):
        """Updates or creates status label over image."""
        if self.status_label:
            self.status_label.destroy()

        self.status_label = self.create_status_label()
        self.status_label.config(text=f"{self.current_image_index + 1}/{self.num_images}")
        self.status_label.place(relx=1.0, rely=0.0, anchor="ne")

    def add_to_cache(self, index, photo_image):
        """Adds an image to the cache, managing cache size."""
        self.image_cache[index] = photo_image
        if len(self.image_cache) > self.cache_size:
            self.manage_cache()

    def manage_cache(self):
        """Keeps the cache within the specified size using LRU (Least Recently Used) eviction."""
        # Sort keys by how far away they are from current index (LRU)
        sorted_keys = sorted(self.image_cache.keys(), key=lambda k: abs(k - self.current_image_index), reverse=True)
        while len(self.image_cache) > self.cache_size:
            key_to_remove = sorted_keys.pop(0)  # remove furtherest image
            del self.image_cache[key_to_remove]
            # print(f"Removed image {key_to_remove} from cache")
        gc.collect()  # force garbage collection

    def prev_image(self, event):
        """Displays the previous image."""
        self.change_image(self.current_image_index - 1)

    def next_image(self, event):
        """Displays the next image."""
        self.change_image(self.current_image_index + 1)

    def change_image(self, new_index):
        """Changes to image at specified index."""
        if 0 <= new_index < self.num_images:
            self.load_and_display_image(new_index)

    def on_mousewheel(self, event):
        """Handles mousewheel scrolling."""
        if event.delta > 0:
            self.change_image(self.current_image_index - 1)  # scroll up goes to previous
        else:
            self.change_image(self.current_image_index + 1)

    def update_scrollbar(self):
        """Updates the scrollbar position and size."""
        start = self.current_image_index / self.num_images
        end = (self.current_image_index + 1) / self.num_images  # +1 to represent current image "width"
        self.scrollbar.set(start, end)

    def scroll_handler(self, *args):
        """Handles scrollbar events."""
        # print(f"Scroll event: {args}")  # Debugging
        command = args[0]
        if command == "moveto":
            # Calculate new index based on scrollbar position
            position = float(args[1])
            new_index = int(position * self.num_images)
            self.change_image(new_index)
        elif command == "scroll":  # Handle clicking on scrollbar arrows
            # args are ('scroll', number of units, 'units' or 'pages')
            value = int(args[1])
            if args[2] == "units":
                self.change_image(self.current_image_index + value)
            elif args[2] == "pages":
                # scroll by 10% of total each click
                self.change_image(self.current_image_index + int(value * self.num_images * 0.1))

    # --- Playback Methods ---
    def toggle_play(self):
        """Toggles play/pause state and updates the button."""
        self.playing = not self.playing
        if self.playing:
            self.toggle_button.config(image=self.pause_icon)  # Show pause icon
            self.play_loop()
        else:
            self.toggle_button.config(image=self.play_icon)  # Show play icon
            if self.after_id:
                self.master.after_cancel(self.after_id)
                self.after_id = None

    def play_loop(self):
        """The main playback loop."""
        if self.playing:
            self.next_image(None)
            if self.current_image_index == self.num_images - 1:
                self.toggle_play()  # Stop at the end and toggle back to play state
                return
            self.after_id = self.master.after(self.play_delay, self.play_loop)


root = tk.Tk()
viewer = ImageViewer(root)
root.mainloop()
