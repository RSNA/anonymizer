import pydicom
import os
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D

# Directory containing DICOM files of the CT scan
directory = "path_to_dicom_files_directory"

# Load DICOM files and extract pixel data
slices = []
for filename in sorted(os.listdir(directory)):
    if filename.endswith(".dcm"):
        ds = pydicom.dcmread(os.path.join(directory, filename))
        slices.append(ds.pixel_array)

# Convert the list of 2D arrays into a 3D NumPy array
volume = np.stack(slices, axis=0)

# Plot the 3D volume
fig = plt.figure()
ax = fig.add_subplot(111, projection='3d')
ax.voxels(volume, edgecolor='k')
ax.set_xlabel('X')
ax.set_ylabel('Y')
ax.set_zlabel('Z')
plt.show()
