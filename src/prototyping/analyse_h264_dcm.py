import pydicom
from pydicom.uid import UID
import os


def inspect_dicom_video_file(filepath):
    try:
        ds = pydicom.dcmread(filepath)
        print(f"--- Inspecting: {filepath} ---")

        # File Meta Information
        print("\n--- File Meta Information ---")
        print(
            f"Media Storage SOP Class UID: {ds.file_meta.MediaStorageSOPClassUID} ({ds.file_meta.MediaStorageSOPClassUID.name})"
        )
        print(f"Media Storage SOP Instance UID: {ds.file_meta.MediaStorageSOPInstanceUID}")
        print(f"Transfer Syntax UID: {ds.file_meta.TransferSyntaxUID} ({ds.file_meta.TransferSyntaxUID.name})")
        print(f"Implementation Class UID: {ds.file_meta.ImplementationClassUID}")
        print(f"Implementation Version Name: {getattr(ds.file_meta, 'ImplementationVersionName', 'N/A')}")

        # Main Dataset - Key Video & General Attributes
        print("\n--- Main Dataset ---")
        print(f"SOP Class UID: {ds.SOPClassUID} ({ds.SOPClassUID.name})")
        print(f"SOP Instance UID: {ds.SOPInstanceUID}")

        print(f"Modality: {getattr(ds, 'Modality', 'N/A')}")
        print(f"Photometric Interpretation: {getattr(ds, 'PhotometricInterpretation', 'N/A')}")
        print(f"Samples Per Pixel: {getattr(ds, 'SamplesPerPixel', 'N/A')}")
        if "PlanarConfiguration" in ds:
            print(f"Planar Configuration: {ds.PlanarConfiguration}")
        else:
            print("Planar Configuration: Not present")

        print(f"Rows: {getattr(ds, 'Rows', 'N/A')}")
        print(f"Columns: {getattr(ds, 'Columns', 'N/A')}")

        print(f"Bits Allocated: {getattr(ds, 'BitsAllocated', 'N/A')}")
        print(f"Bits Stored: {getattr(ds, 'BitsStored', 'N/A')}")
        print(f"High Bit: {getattr(ds, 'HighBit', 'N/A')}")
        print(f"Pixel Representation: {getattr(ds, 'PixelRepresentation', 'N/A')}")

        print(f"Number of Frames: {getattr(ds, 'NumberOfFrames', 'N/A')}")
        print(f"Frame Time (ms): {getattr(ds, 'FrameTime', 'N/A')}")
        if "RecommendedDisplayFrameRate" in ds:
            print(f"Recommended Display Frame Rate: {ds.RecommendedDisplayFrameRate}")
        else:
            print("Recommended Display Frame Rate: Not present")

        if "FrameIncrementPointer" in ds:
            # FrameIncrementPointer is AT, pydicom stores it as a Tag object or list of Tag objects
            fip_val = ds.FrameIncrementPointer
            if isinstance(fip_val, list):  # Multi-valued AT
                print(f"Frame Increment Pointer: {[str(tag) for tag in fip_val]}")
            else:  # Single-valued AT
                print(f"Frame Increment Pointer: {str(fip_val)}")
        else:
            print("Frame Increment Pointer: Not present")

        # Lossy Compression Attributes
        print(f"Lossy Image Compression: {getattr(ds, 'LossyImageCompression', 'N/A')}")
        if "LossyImageCompressionRatio" in ds:
            print(f"Lossy Image Compression Ratio: {ds.LossyImageCompressionRatio}")
        else:
            print("Lossy Image Compression Ratio: Not present")
        if "LossyImageCompressionMethod" in ds:
            print(f"Lossy Image Compression Method: {ds.LossyImageCompressionMethod}")
        else:
            print("Lossy Image Compression Method: Not present")

        if "SpecificCharacterSet" in ds:
            print(f"Specific Character Set: {ds.SpecificCharacterSet}")
        else:
            print("Specific Character Set: Not present")

        # You can add more tags here if you find them relevant from the discussion
        # print(f"Manufacturer: {getattr(ds, 'Manufacturer', 'N/A')}")

    except Exception as e:
        print(f"Error reading or inspecting DICOM file {filepath}: {e}")


if __name__ == "__main__":
    # Replace with the actual path to your downloaded test_720.dcm file
    known_good_dicom_path = "test_720.dcm"
    if os.path.exists(known_good_dicom_path):
        inspect_dicom_video_file(known_good_dicom_path)
    else:
        print(f"Known-good DICOM file not found at: {known_good_dicom_path}")
        print("Please download it (e.g., from the Dropbox link in the discussion) and update the path.")
