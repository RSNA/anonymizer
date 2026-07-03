import tkinter as tk
import customtkinter as ctk
from PIL import Image


class ImageScroller(ctk.CTk):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.title("Lazy Loading Image Scroller")
        self.geometry("300x500")

        # Create a list of dummy images for demonstration purposes
        self.images = []
        for i in range(100):
            img = Image.new("RGB", (100, 100), color=(i * 2, 255 - i * 2, 100))
            self.images.append(img)

        self.image_widgets = {}

        # Create the scrollable frame
        self._ks_frame = ctk.CTkScrollableFrame(self, height=400)
        self._ks_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nswe")

        # Ensure that the scrollable frame resizes properly
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Add a scrollbar to the canvas
        self.scrollbar = ctk.CTkScrollbar(
            self._ks_frame, orientation="vertical", command=self._ks_frame._parent_canvas.yview
        )
        self.scrollbar.grid(row=0, column=1, sticky="ns")

        # Bind the canvas scrolling events
        self._ks_frame._parent_canvas.bind("<Configure>", self.update_visible)
        self._ks_frame._parent_canvas.bind_all("<MouseWheel>", self.scroll_handler)

        # Add a delay before the initial layout update
        self.after(100, self.update_visible)

    def update_visible(self, event=None):
        """Update the visible images when the user scrolls."""
        # Force the layout to be updated first
        self.update_idletasks()

        # Get the frame height and canvas size after layout update
        frame_height = self._ks_frame.winfo_height()
        total_height = len(self.images) * 100  # Total height of images (assuming 100px each)

        if frame_height == 0 or total_height == 0:
            print("Frame height or total image height is 0, retrying.")
            self.after(200, self.update_visible)
            return

        print(f"Frame height: {frame_height}, Total height: {total_height}")

        # Get the visible range based on the canvas yview
        canvas = self._ks_frame._parent_canvas
        yview = canvas.yview()  # Returns a tuple (start, end)

        print(f"Canvas yview: {yview}")

        # Calculate the indices of the visible images
        start_index = int(yview[0] * len(self.images))  # Top of the visible area
        end_index = int(yview[1] * len(self.images))  # Bottom of the visible area

        print(f"Visible range: {start_index} to {end_index}")

        # Remove images outside the visible range
        for index in list(self.image_widgets.keys()):
            if index < start_index or index >= end_index:
                self.image_widgets[index].grid_forget()
                del self.image_widgets[index]

        # Add images in the new visible range
        for index in range(start_index, end_index):
            if index not in self.image_widgets:
                img = self.images[index].resize((100, 100), Image.Resampling.LANCZOS)
                # Convert to CTkImage to avoid warning
                tk_img = ctk.CTkImage(light_image=img, dark_image=img)

                label = ctk.CTkLabel(self._ks_frame, image=tk_img, text="")
                label.grid(row=index, column=0, padx=10, pady=10, sticky="w")

                self.image_widgets[index] = label
                label.image = tk_img  # Retain a reference to the image to avoid garbage collection

    def scroll_handler(self, event):
        """Handle scroll events to trigger image loading."""
        if event.delta > 0:
            # Scroll up
            self._ks_frame._parent_canvas.yview_scroll(-1, "units")
        elif event.delta < 0:
            # Scroll down
            self._ks_frame._parent_canvas.yview_scroll(1, "units")
        self.update_visible()  # Call update_visible when scrolling


if __name__ == "__main__":
    app = ImageScroller()
    app.mainloop()
