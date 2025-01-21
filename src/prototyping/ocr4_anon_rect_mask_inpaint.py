import easyocr
import cv2
import os
import numpy as np


def display_save_images_tiled(images, window_name, save_path):
    padding = 5
    num_images = len(images)
    if num_images == 0:
        print("No images to display.")
        return

    # Determine the best row and column arrangement
    rows = int(np.ceil(np.sqrt(num_images)))
    cols = int(np.ceil(num_images / rows))

    # Create a blank image to hold the tiled images
    height = max(image.shape[0] for image in images) + padding
    width = max(image.shape[1] for image in images) + padding
    canvas = np.zeros((rows * height, cols * width, 3), dtype=np.uint8)

    # Tile the images onto the canvas
    for i, image in enumerate(images):
        row = i // cols
        col = i % cols
        x = col * width + padding
        y = row * height + padding
        canvas[y : y + image.shape[0], x : x + image.shape[1]] = image

    # Save the tiled image
    print(f"Saving tiled images to: {save_path}")
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    cv2.imwrite(save_path, canvas)

    # Display the tiled images
    cv2.imshow(window_name, canvas)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


# Initialize the EasyOCR reader with the desired language(s)
reader = easyocr.Reader(["en"])  # You can add more languages if needed

# Define the source directory containing the images
source_dir = "phi_imgs/input"
results_dir = "phi_imgs/results"

# Get a list of all .jpg .jpeg .png files in the directory
image_files = [f for f in os.listdir(source_dir) if f.lower().endswith((".jpg", ".jpeg", ".png"))]
image_files = sorted(image_files, key=lambda x: os.path.splitext(x)[0])

# Set the border size (in pixels)
border_size = 40

images_text_detected = []
images_anonymized = []

for image_file in image_files:
    print(f"Processing {image_file}")
    # Read the image
    image_path = os.path.join(source_dir, image_file)
    image = cv2.imread(image_path)

    # Add a border to the resized image
    image = cv2.copyMakeBorder(
        image,
        border_size,
        border_size,
        border_size,
        border_size,
        cv2.BORDER_CONSTANT,
        value=[0, 0, 0],  # Black border
    )

    # Perform OCR on the bordered image
    # for word-level detection: width_ths=0.1, paragraph=False
    results = reader.readtext(image)  # , add_margin=0.0)

    # Create a mask for in-painting
    mask = np.zeros(image.shape[:2], dtype=np.uint8)

    # Create a copy of the image to draw black rectangles over text areas
    anonymized_image = image.copy()

    # Draw bounding boxes around each detected word
    for bbox, text, prob in results:
        # Unpack the bounding box
        (top_left, top_right, bottom_right, bottom_left) = bbox

        top_left = tuple(map(int, top_left))
        bottom_right = tuple(map(int, bottom_right))

        # Determine the color of the bounding box based on confidence level
        box_color = (0, 255, 0) if prob >= 0.5 else (255, 0, 0)  # Green if confidence >= 0.5, else Blue

        # Draw the bounding box and the recognized word
        cv2.rectangle(image, top_left, bottom_right, box_color, 2)
        cv2.putText(image, text, (top_left[0], top_left[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, box_color, 2)

        # Fill the mask with white where text is detected
        cv2.rectangle(mask, top_left, bottom_right, (255, 255, 255), -1)

        # cv2.imshow("Mask with Rectangle", mask)
        # cv2.waitKey(0)
        # cv2.destroyAllWindows()

    images_text_detected.append(image)

    # Use in-painting to remove the text while trying to reconstruct the underlying image
    inpainted_image = cv2.inpaint(anonymized_image, mask, inpaintRadius=7, flags=cv2.INPAINT_TELEA)  # cv2.INPAINT_NS)
    images_anonymized.append(inpainted_image)

display_save_images_tiled(
    images_text_detected, "Text Regions Detected by CRAFT", os.path.join(results_dir, "text_detect.jpg")
)
display_save_images_tiled(
    images_anonymized,
    "Anonymized Rectangular Mask Inpaint",
    os.path.join(results_dir, "anonymized_rect_mask_inpaint.jpg"),
)
