import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk


class LazyLoadImageScrollApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Lazy Load Image Scroll")
        self.geometry("300x500")

        # Canvas and Scrollbar Setup
        self.canvas = tk.Canvas(self, width=300, height=500)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas)

        # Create a scrollable window in the canvas
        self.scrollable_frame_id = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        # Pack the canvas and scrollbar
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # Bind events for resizing and scrolling
        self.scrollable_frame.bind("<Configure>", self.update_scrollregion)
        self.canvas.bind("<Configure>", self.update_frame_width)
        self.canvas.bind("<MouseWheel>", self.mouse_scroll)

        # Generate dummy images for lazy loading
        self.images = []
        for i in range(100):
            img = Image.new("RGB", (200, 100), (i * 2 % 256, 100, 255 - i * 2 % 256))
            self.images.append(img)

        # Store visible widgets and range
        self.image_labels = {}
        self.visible_range = (0, 0)

        # Initial rendering
        self.update_visible()

    def update_scrollregion(self, event=None):
        """Update the scroll region of the canvas."""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def update_frame_width(self, event=None):
        """Ensure the frame width matches the canvas width."""
        canvas_width = self.canvas.winfo_width()
        self.canvas.itemconfig(self.scrollable_frame_id, width=canvas_width)

    def mouse_scroll(self, event):
        """Enable mouse wheel scrolling."""
        self.canvas.yview_scroll(-1 * int(event.delta / 120), "units")
        self.update_visible()

    def update_visible(self):
        """Dynamically update visible images in the scrollable frame."""
        canvas_top = self.canvas.canvasy(0)
        canvas_bottom = self.canvas.canvasy(self.canvas.winfo_height())

        img_height = 100  # Each image's height
        start_idx = max(0, int(canvas_top // img_height))
        end_idx = min(len(self.images), int(canvas_bottom // img_height) + 1)

        if self.visible_range == (start_idx, end_idx):
            return  # Range hasn't changed; no need to update
        self.visible_range = (start_idx, end_idx)

        # Add images that should be visible
        for i in range(start_idx, end_idx):
            if i not in self.image_labels:
                img = ImageTk.PhotoImage(self.images[i])
                label = tk.Label(self.scrollable_frame, image=img)
                label.image = img  # Keep reference to avoid garbage collection
                label.grid(row=i, column=0, pady=5)
                self.image_labels[i] = label

        # Remove images that are now off-screen
        for i in list(self.image_labels.keys()):
            if i < start_idx or i >= end_idx:
                self.image_labels[i].destroy()
                del self.image_labels[i]


if __name__ == "__main__":
    app = LazyLoadImageScrollApp()
    app.mainloop()
