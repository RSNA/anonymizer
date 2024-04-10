import pydicom
import matplotlib.pyplot as plt

# Load the DICOM file
ds = pydicom.dcmread(pydicom.data.get_testdata_file("mlut_18.dcm"))

# Access the pixel data
pixel_data = ds.pixel_array

# Plot the image
plt.imshow(pixel_data, cmap="gray")
plt.axis("off")  # Hide axes
plt.show()
