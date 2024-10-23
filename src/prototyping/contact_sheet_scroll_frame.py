import customtkinter as ctk
from PIL import Image, ImageTk

# Create the main window
app = ctk.CTk()
app.geometry("800x600")

# Create a scrollable frame to hold the thumbnails
scroll_frame = ctk.CTkScrollableFrame(app)
scroll_frame.pack(fill="both", expand=True)

# Example list of image paths
image_paths = ["image1.jpg", "image2.jpg", "image3.jpg", "image4.jpg"]

# Function to load thumbnails and display them in a grid
thumbnails = []


def display_thumbnails():
    global thumbnails  # keep a reference to prevent garbage collection
    thumbnails = []
    width = scroll_frame.winfo_width()
    thumbnail_size = 100  # Example thumbnail size
    columns = max(width // thumbnail_size, 1)  # Calculate number of columns

    for i, img_path in enumerate(image_paths):
        image = Image.open(img_path).resize((thumbnail_size, thumbnail_size), Image.ANTIALIAS)
        photo = ImageTk.PhotoImage(image)
        thumbnails.append(photo)
        label = ctk.CTkLabel(scroll_frame, image=photo)
        row = i // columns
        col = i % columns
        label.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")


# Function to update the grid on resize
def on_resize(event):
    display_thumbnails()


# Bind the resize event to the function
scroll_frame.bind("<Configure>", on_resize)

# Initial display of thumbnails
display_thumbnails()

app.mainloop()
