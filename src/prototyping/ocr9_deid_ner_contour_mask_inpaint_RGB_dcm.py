from pathlib import Path
import easyocr
import cv2

import matplotlib.pyplot as plt
import numpy as np
import spacy
import re
from pydicom import Dataset, Sequence, dcmread
from pydicom.pixel_data_handlers.util import apply_modality_lut, apply_voi_lut, apply_color_lut, convert_color_space
from pydicom import config as pydicom_config
from pylibjpeg.utils import get_encoders, get_decoders
from pydicom.uid import JPEG2000Lossless
from openjpeg.utils import encode_array  # JPG2000Lossless
from pydicom.encaps import encapsulate
import logging

logger = logging.getLogger()  # ROOT logger
logging.getLogger("matplotlib").setLevel(logging.ERROR)


def init_logging():
    LOG_FORMAT = "{asctime} {levelname} {threadName} {name}.{funcName}.{lineno} {message}"
    consoleHandler = logging.StreamHandler()
    consoleHandler.setFormatter(logging.Formatter(LOG_FORMAT, style="{"))
    logger.addHandler(consoleHandler)
    logger.setLevel(logging.INFO)
    logging.captureWarnings(True)
    pydicom_config.settings.reading_validation_mode = pydicom_config.IGNORE


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
    # sub_image = cv2.cvtColor(sub_image, cv2.COLOR_BGR2GRAY)
    # Threshold the grayscale sub-image:
    _, thresh = cv2.threshold(sub_image, 0, 255, cv2.THRESH_OTSU)
    # Find contours within the sub-image
    contours, _ = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    # Shift the contours to match the original image coordinates
    for cnt in contours:
        cnt += np.array([x1, y1])
    # Draw the contours on the mask
    cv2.drawContours(mask, contours, -1, (255, 255, 255), thickness=-1)


def has_voi_lut(ds: Dataset):
    # Check for VOILUTSequence
    if "VOILUTSequence" in ds:
        return True
    # Check for WindowCenter and WindowWidth
    if "WindowCenter" in ds and "WindowWidth" in ds:
        return True
    return False


color_spaces = ["RGB", "RGBA", "YBR_FULL", "YBR_FULL_422", "YBR_ICT", "YBR_RCT", "PALETTE COLOR"]


def process_rgb_image(dcm_path: Path, nlp, reader):
    logger.info(f"Processing Multi-channel Image: {dcm_path.name}")

    # Read the DICOM image file using pydicom which will perform any decompression required
    source_ds = dcmread(dcm_path)

    # Extract & validate relevant attributes for pixel data processing:
    # Mandatory:
    pi = source_ds.get("PhotometricInterpretation", None)
    rows = source_ds.get("Rows", None)
    cols = source_ds.get("Columns", None)
    bits_allocated = source_ds.get("BitsAllocated", None)
    bits_stored = source_ds.get("BitsStored", None)
    high_bit = source_ds.get("HighBit", None)
    pixel_representation = source_ds.get("PixelRepresentation", None)
    # Not mandatory:
    pixel_spacing = source_ds.get("PixelSpacing", None)
    no_of_frames = source_ds.get("NumberOfFrames", 1)

    if not pi:
        raise ValueError("PhotometricInterpretation attribute missing")

    if pi not in color_spaces:
        raise ValueError(f"Invalid Photometric Interpretation: {pi}. Expected one of {color_spaces}.")

    if not rows or not cols:
        raise ValueError("Missing image dimensions: Rows & Columns")

    if bits_allocated is None or bits_stored is None or high_bit is None or pixel_representation is None:
        raise ValueError(
            f"Missing essential pixel attributes (BitsAllocated, BitsStored, HighBit, PixelRepresentation)."
        )

    # Validate if bits stored is less than or equal to bits allocated
    if bits_stored > bits_allocated:
        raise ValueError(f"BitsStored ({bits_stored}) cannot be greater than BitsAllocated ({bits_allocated}).")

    # Validate the HighBit value
    if high_bit != bits_stored - 1:
        raise ValueError(f"HighBit ({high_bit}) should be equal to BitsStored - 1 ({bits_stored - 1}).")

    # Validate pixel representation: 0 = unsigned, 1 = signed
    if pixel_representation not in [0, 1]:
        raise ValueError(f"Invalid Pixel Representation: {pixel_representation}. Expected 0 (unsigned) or 1 (signed).")

    # Check that pixel data exists
    if not hasattr(source_ds, "PixelData"):
        raise ValueError("PixelData element is missing.")

    if not pixel_spacing:
        logger.warning("PixelSpacing missing")

    # Decompress source pixel array:
    source_pixels_decompressed = source_ds.pixel_array
    # Copy the decompressed source pixel array:
    pixels = source_pixels_decompressed.copy()

    # Validate Pixel Array:
    # Validate the shape of the Pixel Array
    frame1 = pixels[0] if no_of_frames > 1 else pixels
    if frame1.shape[0] != rows or frame1.shape[1] != cols:
        raise ValueError(f"Pixel array shape {pixels.shape} does not match Rows and Columns ({rows}, {cols}).")

    # Validate the data type
    if bits_allocated == 8:
        expected_dtype = np.uint8 if pixel_representation == 0 else np.int8
    elif bits_allocated == 16:
        expected_dtype = np.uint16 if pixel_representation == 0 else np.int16
    else:
        raise ValueError("Unsupported BitsAllocated value. Only 8 and 16 bits are supported.")

    if pixels.dtype != expected_dtype:
        raise ValueError(f"Pixel data type {pixels.dtype} does not match expected type {expected_dtype}.")

    # Validate pixel value range according to BitsStored
    max_valid_value = (1 << bits_stored) - 1
    if pixel_representation == 0:  # unsigned
        if np.any(pixels < 0) or np.any(pixels > max_valid_value):
            raise ValueError(
                f"Pixel values out of range for BitsStored ({bits_stored}): Found range [{pixels.min()}, {pixels.max()}]."
            )
    else:  # signed
        min_valid_value = -(1 << (bits_stored - 1))
        max_valid_value = (1 << (bits_stored - 1)) - 1
        if np.any(pixels < min_valid_value) or np.any(pixels > max_valid_value):
            raise ValueError(
                f"Pixel values out of range for signed BitsStored ({bits_stored}): Found range [{pixels.min()}, {pixels.max()}]."
            )

    # DICOM grayscale image validated

    logging.info(f"Header and pixel array valid, now processing...")
    logger.info(f"Transfer Syntax: {source_ds.file_meta.TransferSyntaxUID}")
    logger.info(f"Compressed: {source_ds.file_meta.TransferSyntaxUID.is_compressed}")
    logger.info(f"PhotometricInterpretation: {pi}")
    logger.info(f"Rows={rows} Columns={cols}")
    logger.info(
        f"BitsAllocated={bits_allocated} BitStored={bits_stored} HighBit={high_bit} Signed={pixel_representation!=0}"
    )
    logger.info(f"pixels.shape: {pixels.shape}")
    logger.info(f"pixels.value.range:[{pixels.min(), pixels.max()}]")
    logger.info(f"Pixel Spacing: {pixel_spacing}")
    logger.info(f"Number of Frames: {no_of_frames}")

    # *BEGIN PROCESSING*:
    # GET REDCACTION CONTOURS TO APPLY TO SOURCE PIXELS

    # # Apply Color LUT if photometric interpretation is PALETTE COLOR
    # if photometric_interpretation == "PALETTE COLOR" and "PaletteColorLookupTableData" in dicom_file:
    #     pixel_array = apply_color_lut(pixel_array, dicom_file)

    # # Convert color space if needed (e.g., from YBR to RGB)
    # elif photometric_interpretation in ["YBR_FULL", "YBR_FULL_422", "YBR_ICT", "YBR_RCT"]:
    #     pixel_array = convert_color_space(pixel_array, dicom_file)

    if no_of_frames == 1:
        pixels_stack = [pixels]
        source_pixels_decompressed_stack = [source_pixels_decompressed]
    else:
        pixels_stack = pixels
        source_pixels_decompressed_stack = source_pixels_decompressed

    # To improve OCR processing speed:
    # TODO: Work out more precisely using readable text size, pixel spacing (not always present), mask blur kernel size & inpainting radius
    # Downscale the image if its width exceeds the widht_threshold
    widht_threshold = 1200
    scale_factor = 1
    downscale = cols > widht_threshold
    if downscale:
        scale_factor = widht_threshold / cols

    border_size = 40  # pixels

    source_pixels_deid_stack = []

    for frame in range(no_of_frames):

        if no_of_frames > 1:
            logging.info(f"Processing Frame {frame}...")

        pixels = pixels_stack[frame]

        # Display Source Pixels using Matplotlib because cv2.imshow handles 8bit only
        # plt.imshow(pixels, cmap="gray")
        # plt.title(f"Source Image Frame {frame}")
        # plt.axis("off")
        # plt.show()

        # Apply Value of Interest Lookup if present:
        # TODO: is this necessary?
        if has_voi_lut(source_ds):
            pixels = apply_voi_lut(pixels, source_ds)
            logger.info(f"Apply VOI LUT: new pixels.value.range:[{pixels.min(), pixels.max()}]")

        # Normalize the pixel array to the range 0-255
        cv2.normalize(src=pixels, dst=pixels, alpha=0, beta=255, norm_type=cv2.NORM_MINMAX, dtype=-1, mask=None)
        pixels = pixels.astype(np.uint8)
        logger.info(f"After normalization: pixels.value.range:[{pixels.min(), pixels.max()}]")

        if downscale:
            new_size = (widht_threshold, int(rows * scale_factor))
            pixels = cv2.resize(pixels, new_size, interpolation=cv2.INTER_LINEAR)
            logger.info(f"Downscaled image, new pixels.shape: {pixels.shape}")
        else:
            logger.info(f"Image width < {widht_threshold}, no downscaling required.")

        # Add a border to the resized image
        pixels = cv2.copyMakeBorder(
            pixels,
            border_size,
            border_size,
            border_size,
            border_size,
            cv2.BORDER_CONSTANT,
            value=[0, 0, 0],  # Black border
        )
        logger.info(f"Black Border of {border_size}px added, new pixels.shape: {pixels.shape}")

        # Perform OCR on the bordered image
        # for word-level detection: width_ths=0.1, paragraph=False
        results = reader.readtext(pixels, add_margin=0.0, rotation_info=[90])  # , 180, 270])

        if not results:
            logger.info("No text found in frame")
            continue

        logger.info(f"Text boxes detected in frame: {len(results)}")

        # Create a mask for in-painting
        mask = np.zeros(pixels.shape[:2], dtype=np.uint8)

        # Intermediate Images for debugging/verification
        # text_detect_image = pixels.copy()

        # Draw bounding boxes around each detected word
        for bbox, text, prob in results:

            # Unpack the bounding box
            (top_left, top_right, bottom_right, bottom_left) = bbox

            top_left = tuple(map(int, top_left))
            bottom_right = tuple(map(int, bottom_right))

            # Text Detection Image:
            # Determine the color of the bounding box based on confidence level
            # Draw the bounding box and the recognized word
            # box_color = (255, 255, 255)
            # cv2.rectangle(text_detect_image, top_left, bottom_right, box_color, 2)
            # cv2.putText(
            #     text_detect_image, text, (top_left[0], top_left[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, box_color, 2
            # )

            # If nlp absent, peform full anonymization, remove all detected text from image:
            if nlp is None:
                draw_text_contours_on_mask(pixels, top_left, bottom_right, mask)
                continue

            # Perform Named Entity Recognition using the supplied spacy nlp object:
            # 1. Spacy
            doc = nlp(text)  # TODO: Fuzzy match, EntityRuler et.al.
            entities = [ent.label_ for ent in doc.ents]

            # Add rectangle to mask if any target entities detect in text:
            if any(entity in entities for entity in ["PERSON", "DATE", "GPE", "LOC"]):
                # logger.info(f"spacer ner entities {entities} detected in {text}")
                draw_text_contours_on_mask(pixels, top_left, bottom_right, mask)
                continue

            # 2. MRN Check:
            if mrn_probability(text) > 0.5:
                # logger.info(f"MRN probable in {text}")
                draw_text_contours_on_mask(pixels, top_left, bottom_right, mask)
                continue

            # 3. DATE Check:
            if date_probability(text) > 0.5:
                # logger.info(f"DATE probable in {text}")
                draw_text_contours_on_mask(pixels, top_left, bottom_right, mask)
                continue

        # # blurred_mask = cv2.GaussianBlur(src=mask, ksize=(7, 7), sigmaX=0)
        # kernel = np.ones((3, 3), np.uint8)
        # dilated_mask = cv2.dilate(src=mask, kernel=kernel, iterations=1)
        # # Use in-painting to remove the text while preserving the underlying image
        # inpainted_image = cv2.inpaint(
        #     src=deid_image, inpaintMask=dilated_mask, inpaintRadius=5, flags=cv2.INPAINT_TELEA
        # )  # cv2.INPAINT_NS)

        # cv2.imshow("Source", pixels)
        # cv2.waitKey(0)
        # cv2.imshow("Text Detect", text_detect_image)
        # cv2.waitKey(0)

        # CHANGE SOURCE PIXELS:
        # Apply inpainting mask to source pixel array:
        # Remove border from mask
        mask = mask[border_size:-border_size, border_size : mask.shape[1] - border_size]
        logger.info(f"Remove Border from mask, new mask.shape: {mask.shape}")

        # Upscale mask if downscaling was applied to source image:
        if scale_factor < 1:
            mask = cv2.resize(src=mask, dsize=(cols, rows), interpolation=cv2.INTER_LINEAR)
            logger.info(f"Upscale mask back to original source image size, new mask.shape: {mask.shape}")

        kernel = np.ones((3, 3), np.uint8)
        dilated_mask = cv2.dilate(src=mask, kernel=kernel, iterations=1)

        # cv2.imshow("Mask", mask)
        # cv2.waitKey(0)
        # cv2.imshow("Dilated Mask", dilated_mask)
        # cv2.waitKey(0)

        source_pixels_deid = cv2.inpaint(
            src=source_pixels_decompressed_stack[frame],
            inpaintMask=dilated_mask,
            inpaintRadius=5,
            flags=cv2.INPAINT_TELEA,
        )

        # plt.imshow(source_pixels_deid, cmap="gray")
        # plt.title("De-identified Source Image")
        # plt.axis("off")
        # plt.show()

        # if source pixels were compressed then re-compress to JPG2000Lossless:
        if source_ds.file_meta.TransferSyntaxUID.is_compressed:
            logger.info("Re-compress deidentified source frame")
            source_pixels_deid = encode_array(arr=source_pixels_deid, photometric_interpretation=2, use_mct=False)

        source_pixels_deid_stack.append(source_pixels_deid)

    # Save processed stack to DICOM file:
    if source_ds.file_meta.TransferSyntaxUID.is_compressed:
        source_ds.PixelData = encapsulate(source_pixels_deid_stack)
        source_ds["PixelData"].is_undefined_length = True
        source_ds.file_meta.TransferSyntaxUID = JPEG2000Lossless
    else:
        source_ds.PixelData = np.stack(source_pixels_deid_stack, axis=0).tobytes()

    # pydicom only supports RLELossless encoding
    # source_ds.compress(RLELossless, arr=source_pixels_processed)

    # Save image as DICOM with original compression:
    results_dir = dcm_path.parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    output_path = results_dir / (str(dcm_path.name) + ".deid")
    source_ds.save_as(output_path)  # , write_like_original=False)

    # Read back result file, decompress and display:
    # ds = dcmread(output_path)
    # plt.imshow(ds.pixel_array, cmap="gray")
    # plt.axis("off")
    # plt.show()


def main():
    init_logging()
    logger.info(f"{Path(__file__).stem} start")

    logger.info(f"pylibjpeg decoders: {get_decoders()}")
    logger.info(f"pylibjpeg encoders: {get_encoders()}")

    # Initialize the EasyOCR reader with the desired language(s)
    reader = easyocr.Reader(["en"])  # for full range of Roman char sets include: de,fr,es

    # Load the spacy model
    nlp = None  # spacy.load("en_core_web_trf")  # "en_core_web_sm"

    # Define the source directory containing the images
    # source_dir = Path("/Users/michaelevans/Documents/TCI-PSEUDO-PHI")
    source_dir = Path("/Users/michaelevans/Documents/CODE/RSNA/anonymizer/phi_imgs/test_dcm_1")

    # Get a list of all DICOM files in the source directory tree:
    p = source_dir.glob(f"**/*.dcm")
    dcm_files = [x for x in p if x.is_file()]

    if not dcm_files:
        logger.info("No DICOM files found in source directory")
        return

    # Iterate through dicom file paths:
    for dcm_file in dcm_files:
        process_rgb_image(dcm_file, nlp, reader)


if __name__ == "__main__":
    main()
