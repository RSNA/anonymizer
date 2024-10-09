import easyocr
import cv2
import matplotlib.pyplot as plt
import os
import tkinter as tk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np

# Initialize the EasyOCR reader with the desired language(s)
reader = easyocr.Reader(["en"])  # You can add more languages if needed

# Define the source directory containing the images
source_dir = "phi_imgs/input_1"  # Replace with the actual path to your image directory

# Get a list of all .jpg files in the directory
image_files = [f for f in os.listdir(source_dir) if f.endswith(".jpg")]

# Set the border size (in pixels)
border_size = 20

# Set desired maximum dimensions for resizing (keeping aspect ratio)
max_width = 800
max_height = 800

# Create a list to store processed images for display
processed_images = []

for image_file in image_files:
    # Read the image
    image_path = os.path.join(source_dir, image_file)
    image = cv2.imread(image_path)

    # Resize the image while maintaining aspect ratio
    h, w = image.shape[:2]
    scaling_factor = min(max_width / w, max_height / h)
    new_size = (int(w * scaling_factor), int(h * scaling_factor))
    resized_image = cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)

    # Add a border to the resized image
    bordered_image = cv2.copyMakeBorder(
        resized_image,
        border_size,
        border_size,
        border_size,
        border_size,
        cv2.BORDER_CONSTANT,
        value=[255, 255, 255],  # White border
    )

    # Perform OCR on the bordered image
    results = reader.readtext(bordered_image, paragraph=False)  # Set paragraph=False for word-level detection

    # Draw bounding boxes around each detected word
    for bbox, text, prob in results:
        # Unpack the bounding box
        (top_left, top_right, bottom_right, bottom_left) = bbox
        top_left = tuple(map(int, top_left))
        bottom_right = tuple(map(int, bottom_right))

        # Determine the color of the bounding box based on confidence level
        box_color = (0, 255, 0) if prob >= 0.5 else (255, 0, 0)  # Green if confidence >= 0.5, else Red

        # Draw the bounding box and the recognized word
        cv2.rectangle(bordered_image, top_left, bottom_right, box_color, 2)
        cv2.putText(bordered_image, text, (top_left[0], top_left[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, box_color, 2)

    # Convert image from BGR to RGB format for displaying with Matplotlib
    image_rgb = cv2.cvtColor(bordered_image, cv2.COLOR_BGR2RGB)

    # Add the processed image to the list
    processed_images.append(image_rgb)

# Set up the Tkinter window
root = tk.Tk()
root.title("OCR Results")

# Create a canvas widget
canvas = tk.Canvas(root)
canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

# Add a scrollbar to the canvas
scrollbar = tk.Scrollbar(root, orient=tk.VERTICAL, command=canvas.yview)
scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
canvas.configure(yscrollcommand=scrollbar.set)

# Create a frame inside the canvas
frame = tk.Frame(canvas)
canvas.create_window((0, 0), window=frame, anchor="nw")

# Set up the Matplotlib figure with 3 images per row
num_images = len(processed_images)
cols = 1  # images per row
rows = (num_images // cols) + (num_images % cols > 0)

fig, axes = plt.subplots(rows, cols, figsize=(15, 3 * rows))

# Flatten the axes array safely using np.ravel()
axes = np.ravel(axes)

# Remove extra white space around the images
plt.subplots_adjust(wspace=0.05, hspace=0.05, left=0.02, right=0.98, top=0.98, bottom=0.02)

# Plot each processed image on its own axis
for i in range(num_images):
    axes[i].imshow(processed_images[i])
    axes[i].axis("off")  # Hide the axis

# Hide any unused subplots
for j in range(num_images, len(axes)):
    axes[j].axis("off")

# Embed the Matplotlib figure into the Tkinter canvas
canvas_agg = FigureCanvasTkAgg(fig, master=frame)
canvas_agg.draw()
canvas_agg.get_tk_widget().pack()

# Update the scroll region to encompass the whole frame
frame.update_idletasks()
canvas.config(scrollregion=canvas.bbox("all"))

root.mainloop()
