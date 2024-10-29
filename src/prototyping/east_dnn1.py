import cv2
import numpy as np


# nms_threshold: higher value => more boxes retained
def detect_text_boxes(image_path, model_path, conf_threshold=0.5, nms_threshold=0.4):
    # Load the pre-trained EAST model
    net = cv2.dnn.readNet(model_path)

    # Read the input image
    image = cv2.imread(image_path)  # BGR color space
    original_height, original_width = image.shape[:2]

    # Set the new width and height to multiple of 32 (required by EAST)
    new_width = (original_width // 32) * 32
    new_height = (original_height // 32) * 32

    # Resize the image
    resized_image = cv2.resize(image, (new_width, new_height))

    # Prepare the blob for the input image
    # blob = cv2.dnn.blobFromImage(
    #     resized_image, 1.0, (new_width, new_height), (123.68, 116.78, 103.94), swapRB=True, crop=False
    # )

    # For grayscale images
    blob = cv2.dnn.blobFromImage(
        resized_image,  # The input grayscale image
        1.0,  # Scale factor (no scaling)
        (new_width, new_height),  # Resized dimensions
        0,  # Mean value (for single channel, you can use 0)
        swapRB=False,  # No need to swap channels for grayscale
        crop=False,  # Do not crop
    )

    net.setInput(blob)

    # Get the output layer names
    output_layers = ["feature_fusion/Conv_7/Sigmoid", "feature_fusion/concat_3"]

    # Forward pass to get the outputs
    scores, geometry = net.forward(output_layers)

    # Decode the results
    boxes, confidences = decode_predictions(scores, geometry, conf_threshold)

    # Apply non-maximum suppression to filter overlapping boxes
    indices = cv2.dnn.NMSBoxes(boxes, confidences, conf_threshold, nms_threshold)

    # Check if indices is not empty and extract final boxes
    final_boxes = []
    if len(indices) > 0:
        for i in indices:
            final_boxes.append(boxes[i[0]] if isinstance(i, (list, np.ndarray)) else boxes[i])

    # Draw the detected boxes on the original image
    for startX, startY, endX, endY in final_boxes:
        # Scale the coordinates back to the original image size
        startX = int(startX * original_width / new_width)
        startY = int(startY * original_height / new_height)
        endX = int(endX * original_width / new_width)
        endY = int(endY * original_height / new_height)

        # Draw the rectangle
        cv2.rectangle(image, (startX, startY), (endX, endY), (0, 255, 0), 2)

    # Display the image with detected boxes
    cv2.imshow("Text Detection", image)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


def decode_predictions(scores, geometry, conf_threshold):
    # Get the number of rows and columns from the score map
    num_rows, num_cols = scores.shape[2:4]
    boxes = []
    confidences = []

    for y in range(num_rows):
        scores_data = scores[0, 0, y]
        x0_data = geometry[0, 0, y]
        x1_data = geometry[0, 1, y]
        x2_data = geometry[0, 2, y]
        x3_data = geometry[0, 3, y]
        angles_data = geometry[0, 4, y]

        for x in range(num_cols):
            score = scores_data[x]

            if score < conf_threshold:
                continue

            # Calculate the offset
            offset_x = x * 4.0
            offset_y = y * 4.0

            # Extract the rotation angle for the bounding box
            angle = angles_data[x]
            cos = np.cos(angle)
            sin = np.sin(angle)

            # Calculate the bounding box width and height
            h = x0_data[x] + x2_data[x]
            w = x1_data[x] + x3_data[x]

            # Calculate the end coordinates for the bounding box
            end_x = int(offset_x + (cos * x1_data[x]) + (sin * x2_data[x]))
            end_y = int(offset_y - (sin * x1_data[x]) + (cos * x2_data[x]))
            start_x = int(end_x - w)
            start_y = int(end_y - h)

            # Append the box and confidence score
            boxes.append((start_x, start_y, end_x, end_y))
            confidences.append(float(score))

    return boxes, confidences


# Example usage
image_path = "phi_imgs/input_1/cxr7_lo.jpg"
model_path = "src/assets/ocr/model/frozen_east_text_detection.pb"
detect_text_boxes(image_path, model_path)
