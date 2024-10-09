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
source_dir = "phi_imgs/input_2"
results_dir = "phi_imgs/results_2"

# Get a list of all .jpg .jpeg .png files in the directory
image_files = [f for f in os.listdir(source_dir) if f.lower().endswith((".jpg", ".jpeg", ".png"))]
image_files = sorted(image_files, key=lambda x: os.path.splitext(x)[0])

# Set the border size (in pixels)
border_size = 40

source_images = []
images_anonymized = []

for image_file in image_files:
    print(f"Processing {image_file}")
    # Read the image
    image_path = os.path.join(source_dir, image_file)
    source_image = cv2.imread(image_path)

    image = source_image.copy()

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
    results = reader.readtext(image)  # , width_ths=0.1)  # Set paragraph=False for word-level detection

    # Create a mask for in-painting
    mask = np.zeros(image.shape[:2], dtype=np.uint8)

    # Draw bounding boxes around each detected word
    for bbox, text, prob in results:
        # Unpack the bounding box
        (top_left, top_right, bottom_right, bottom_left) = bbox  # coordinates [i,j]

        top_left = tuple(map(int, top_left))  # to tuple (i,j)
        bottom_right = tuple(map(int, bottom_right))

        # Extracting coordinates
        x1, y1 = top_left
        x2, y2 = bottom_right

        if x2 - x1 < 10 or y2 - y1 < 10:
            continue

        # Constructing the sub-image
        sub_image = image[y1:y2, x1:x2]

        # cv2.imshow("Sub-Image", sub_image)
        # cv2.waitKey(0)

        # Convert sub_image to grayscale for contour detection
        gray_sub_image = cv2.cvtColor(sub_image, cv2.COLOR_BGR2GRAY)

        # cv2.imshow("Gray Sub-Image", gray_sub_image)
        # cv2.waitKey(0)

        # Threshold the grayscale sub-image:
        _, thresh = cv2.threshold(gray_sub_image, 0, 255, cv2.THRESH_OTSU)

        # cv2.imshow("Gray Sub-Image thresholded", thresh)
        # cv2.waitKey(0)

        # Find contours within the sub-image
        contours, _ = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        # cv2.drawContours(thresh, contours, -1, (255, 255, 255), thickness=-1)
        # cv2.imshow("Gray Sub-Image thresholded with Contours", thresh)
        # cv2.waitKey(0)

        # Filter contours based on area - remove the outer rectangle
        # filtered_contours = [cnt for cnt in contours if cv2.contourArea(cnt) < 0.8 * (x2 - x1) * (y2 - y1)]

        # Shift the contours to match the original image coordinates
        for cnt in contours:
            cnt += np.array([x1, y1])

        # Draw the contours on the mask
        cv2.drawContours(mask, contours, -1, (255, 255, 255), thickness=-1)

    # cv2.imshow("Mask with Contours", mask)
    # cv2.waitKey(0)
    # cv2.destroyAllWindows()

    # Apply dilation to the mask
    # Define the kernel (structuring element) for dilation
    kernel = np.ones((4, 4), np.uint8)  # This creates a 3x3 matrix of ones, which acts as the dilation kernel
    mask_dilated = cv2.dilate(mask, kernel, iterations=1)  # You can increase iterations if needed
    blurred_mask = cv2.GaussianBlur(mask, (5, 5), 0)
    # Use in-painting to remove the text while preserving the underlying image
    inpainted_image = cv2.inpaint(src=image, inpaintMask=blurred_mask, inpaintRadius=7, flags=cv2.INPAINT_TELEA)

    source_images.append(source_image)
    images_anonymized.append(inpainted_image)

display_save_images_tiled(
    source_images,
    "PHI Burnt-IN Image Samples from Gemini & Meta AI",
    os.path.join(results_dir, "sample_images_generated.jpg"),
)

display_save_images_tiled(
    images_anonymized,
    "Anonymized Contour Mask Inpaint",
    os.path.join(results_dir, "anonymized_contour_inpainted.jpg"),
)
