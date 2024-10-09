import easyocr
import cv2
import os
import numpy as np
import spacy
import re

# Load the spacy model
nlp = spacy.load("en_core_web_trf")  # "en_core_web_sm"


def mrn_probability(text: str) -> float:
    """
    Detects the probability of a given text containing a Medical Record Number (MRN) or medical identifier.

    Args:
        text (str): Input text string.

    Returns:
        float: Probability score between 0 and 1.
    """
    # Define regex patterns for common MRN structures (adjust based on specific use case)
    mrn_patterns = [
        r"\b\d{6,15}\b",  # A sequence of 6 to 10 digits (standard MRN length)
        r"\b(MRN|ID|PatientID)\s*[:\-]?\s*\d{6,10}\b",  # MRN/ID prefix followed by digits
        r"\b[A-Z]{2,3}\d{6,8}\b",  # Alphanumeric, 2-3 letters followed by digits
        # Optional: Consider numeric/alphanumeric MRNs with known prefixes
        r"\b\d{2,4}-\d{2,4}-\d{2,4}\b",  # Example for structured MRN format (like 1234-5678-9012)
    ]

    # Contextual alphanumeric MRN patterns: Only detect alphanumerics if followed by a digit
    alphanumeric_mrn_pattern = r"\b[A-Z]{1,3}\d{6,8}\b"  # Refined to expect some digits after letters

    # Compile all patterns into one
    combined_mrn_pattern = "|".join(mrn_patterns)

    # Search for all MRN-like matches in the text
    matches = re.findall(combined_mrn_pattern, text)

    # Initialize base confidence score
    if len(matches) == 0:
        return 0.0  # No MRN-like patterns detected

    base_confidence = 0.5  # Start with a base confidence

    # Boost confidence for more complex MRN structures (like prefixes or alphanumeric codes)
    complex_mrn_patterns = [r"\b(MRN|ID|PatientID)", alphanumeric_mrn_pattern]
    for pattern in complex_mrn_patterns:
        if re.search(pattern, text):
            base_confidence += 0.2  # Add confidence for each complex structure

    # Increase confidence slightly for multiple matches
    confidence = min(1.0, base_confidence + 0.1 * len(matches))  # Cap the score at 1.0

    return confidence


def date_probability(text):
    # Regex patterns to match a wide variety of date formats
    date_patterns = [
        r"\b\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4}\b",  # DD-MM-YYYY, MM/DD/YY, etc.
        r"\b\d{2,4}[-/\.]\d{1,2}[-/\.]\d{1,2}\b",  # YYYY/MM/DD, YYYY.MM.DD, etc.
        r"\b\d{1,2}\s(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s\d{2,4}\b",  # DD Month YYYY
        r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s\d{1,2},\s\d{2,4}\b",  # Month DD, YYYY
        r"\b\d{1,2}(st|nd|rd|th)?\s(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s\d{2,4}\b",  # 1st January 2024
        r"\b\d{4}\b",  # Standalone year (YYYY)
    ]

    # Compile all patterns into one
    combined_pattern = "|".join(date_patterns)

    # Search for all matches in the text
    matches = re.findall(combined_pattern, text)

    # Determine confidence based on the number of matches and complexity
    if len(matches) == 0:
        return 0.0  # No date-like patterns detected

    # Factors influencing confidence:
    # 1. Presence of a match increases confidence
    # 2. Multiple patterns detected increase confidence
    # 3. Complex patterns (with month names or ordinal numbers) give higher confidence

    base_confidence = 0.6  # Base confidence if at least one match is found

    # Increase confidence for complex patterns
    complex_patterns = [r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", r"\d{1,2}(st|nd|rd|th)"]
    for pattern in complex_patterns:
        if re.search(pattern, text):
            base_confidence += 0.2  # Add confidence for complex formats

    # Adjust confidence for the number of detected date patterns
    confidence = min(1.0, base_confidence + 0.1 * len(matches))  # Cap confidence at 1.0

    return confidence


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


def draw_text_contours_on_mask(image, top_left, bottom_right, mask):
    # Sub-image contour masking:
    # Extracting coordinates
    x1, y1 = top_left
    x2, y2 = bottom_right
    # Skip small rectangles:
    if x2 - x1 < 10 or y2 - y1 < 10:
        return
    # Constructing sub-image
    sub_image = image[y1:y2, x1:x2]
    # Convert sub_image to grayscale for contour detection
    gray_sub_image = cv2.cvtColor(sub_image, cv2.COLOR_BGR2GRAY)
    # Threshold the grayscale sub-image:
    _, thresh = cv2.threshold(gray_sub_image, 0, 255, cv2.THRESH_OTSU)
    # Find contours within the sub-image
    contours, _ = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    # Shift the contours to match the original image coordinates
    for cnt in contours:
        cnt += np.array([x1, y1])
    # Draw the contours on the mask
    cv2.drawContours(mask, contours, -1, (255, 255, 255), thickness=-1)


# Initialize the EasyOCR reader with the desired language(s)
reader = easyocr.Reader(["en"])  # You can add more languages if needed

# Define the source directory containing the images
source_dir = "phi_imgs/input_1"
results_dir = "phi_imgs/results_1"

# Get a list of all .jpg .jpeg .png files in the directory
image_files = [f for f in os.listdir(source_dir) if f.lower().endswith((".jpg", ".jpeg", ".png"))]
image_files = sorted(image_files, key=lambda x: os.path.splitext(x)[0])

# Set the border size (in pixels)
border_size = 40

source_images = []
images_text_detected = []
images_deidentified = []

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
    # for word-level detection: width_ths=0.1, paragraph=False
    results = reader.readtext(image, add_margin=0.0, rotation_info=[90])  # , 180, 270])

    # Create a mask for in-painting
    mask = np.zeros(image.shape[:2], dtype=np.uint8)

    text_detect_image = image.copy()
    deid_image = image.copy()

    # Draw bounding boxes around each detected word
    for bbox, text, prob in results:

        # print(text)

        # Unpack the bounding box
        (top_left, top_right, bottom_right, bottom_left) = bbox

        top_left = tuple(map(int, top_left))
        bottom_right = tuple(map(int, bottom_right))

        # Text Detection Image:
        # Determine the color of the bounding box based on confidence level
        box_color = (0, 255, 0) if prob >= 0.5 else (255, 0, 0)  # Green if confidence >= 0.5, else Blue
        # Draw the bounding box and the recognized word
        cv2.rectangle(text_detect_image, top_left, bottom_right, box_color, 2)
        cv2.putText(
            text_detect_image, text, (top_left[0], top_left[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, box_color, 2
        )

        # NER:
        # 1. Spacy
        doc = nlp(text)  # TODO: Fuzzy match, EntityRuler et.al.
        entities = [ent.label_ for ent in doc.ents]
        # words = text.split(r"[ .;^]")
        # for word in words:
        #     doc = nlp(word)
        #     for ent in doc.ents:
        #         if ent.label_ not in entities:
        #             entities.append(ent.label_)

        # Add rectangle to mask if any target entities detect in text:
        if any(entity in entities for entity in ["PERSON", "DATE", "GPE", "LOC"]):
            # print(f"spacer ner entities {entities} detected in {text}")
            draw_text_contours_on_mask(image, top_left, bottom_right, mask)
            continue

        # 2. MRN Check:
        if mrn_probability(text) > 0.5:
            # print(f"MRN probable in {text}")
            draw_text_contours_on_mask(image, top_left, bottom_right, mask)
            continue

        # 3. DATE Check:
        if date_probability(text) > 0.5:
            # print(f"DATE probable in {text}")
            draw_text_contours_on_mask(image, top_left, bottom_right, mask)
            continue

    # Apply dilation to the mask
    # Define the kernel (structuring element) for dilation
    # kernel = np.ones((4, 4), np.uint8)  # This creates a 3x3 matrix of ones, which acts as the dilation kernel
    # mask_dilated = cv2.dilate(mask, kernel, iterations=1)  # You can increase iterations if needed
    blurred_mask = cv2.GaussianBlur(mask, (5, 5), 0)
    # Use in-painting to remove the text while preserving the underlying image
    inpainted_image = cv2.inpaint(
        src=deid_image, inpaintMask=blurred_mask, inpaintRadius=7, flags=cv2.INPAINT_TELEA
    )  # cv2.INPAINT_NS)

    images_text_detected.append(text_detect_image)
    images_deidentified.append(inpainted_image)
    source_images.append(source_image)

display_save_images_tiled(
    source_images,
    "PHI Burnt-IN Image Samples",
    os.path.join(results_dir, "source_sample_images.jpg"),
)
display_save_images_tiled(
    images_text_detected, "Text Regions Detected by CRAFT", os.path.join(results_dir, "text_detect.jpg")
)
display_save_images_tiled(
    images_deidentified,
    "De-identified Spacy/Date/MRN Contour Mask",
    os.path.join(results_dir, "deid_ner_contour_inpaint.jpg"),
)
