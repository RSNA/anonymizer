import copy  # For deepcopy
import os

import ffmpeg
import numpy as np
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.encaps import encapsulate
from pydicom.uid import PYDICOM_IMPLEMENTATION_UID, UID, ExplicitVRLittleEndian, generate_uid


def transcode_dicom_to_h264_dicom(
    input_dicom_path: str, output_dicom_path: str, output_width: int, output_height: int, crf_value: int = 23
):
    try:
        ds = pydicom.dcmread(input_dicom_path)
    except Exception as e:
        print(f"Error reading DICOM file {input_dicom_path}: {e}")
        return

    original_ts_uid_for_error_reporting = ds.file_meta.TransferSyntaxUID

    try:
        pixel_array = ds.pixel_array  # Relies on pydicom to handle decompression
    except Exception as e:
        print(f"Error extracting pixel array from {input_dicom_path}: {e}")
        print("This can occur if pixel data is missing, corrupt, or if the DICOM file is compressed ")
        print("and the required pydicom handlers (e.g., pylibjpeg, python-gdcm, pillow) are not installed.")
        print(f"The file's original Transfer Syntax was: {original_ts_uid_for_error_reporting}")
        return

    if len(pixel_array.shape) == 2:
        num_frames = 1
        pixel_array_for_processing = pixel_array[np.newaxis, :, :]
    elif len(pixel_array.shape) == 3:
        num_frames = pixel_array.shape[0]
        pixel_array_for_processing = pixel_array
    else:
        print(f"Unsupported pixel array shape: {pixel_array.shape} in {input_dicom_path}")
        return

    if num_frames == 0:
        print(f"No frames found in {input_dicom_path}")
        return

    input_rows = ds.Rows
    input_cols = ds.Columns

    if ds.PhotometricInterpretation == "MONOCHROME1":
        print("MONOCHROME1 DICOM detected. Inverting pixel values for video display compatibility.")
        max_val = (
            (2**ds.BitsStored - 1)
            if ds.BitsStored > 0 and ds.BitsStored <= pixel_array_for_processing.itemsize * 8
            else pixel_array_for_processing.max()
        )
        if max_val == 0:
            print("Warning: Max pixel value for MONOCHROME1 inversion is 0. Pixels will not be inverted.")
        else:
            pixel_array_for_processing = max_val - pixel_array_for_processing
            pixel_array_for_processing = np.clip(pixel_array_for_processing, 0, max_val).astype(
                pixel_array_for_processing.dtype
            )

    ffmpeg_pix_fmt_in = ""
    # --- NEW: Convert 16-bit (0-4095 range) to 8-bit (0-255 range) grayscale IN PYTHON ---
    if ds.BitsAllocated == 16:
        print("Debug: Converting 16-bit input (0-4095 range) to 8-bit (0-255 range) for FFmpeg.")
        # Scale 0-4095 to 0-255.
        # Ensure to handle the case where BitsStored might be less than 12,
        # but ds.pixel_array should already give values in the actual intensity range.
        # Current min/max is 66/3583. We scale this range to 0-255.
        # A simple linear scaling:
        min_val = pixel_array_for_processing.min()
        max_val = pixel_array_for_processing.max()
        if max_val == min_val:  # Avoid division by zero if flat image
            pixel_array_8bit = np.zeros_like(pixel_array_for_processing, dtype=np.uint8)
        else:
            # Scale to 0-1 then to 0-255
            pixel_array_norm = (pixel_array_for_processing - min_val) / (max_val - min_val)
            pixel_array_8bit = (pixel_array_norm * 255).astype(np.uint8)

        pixel_array_for_ffmpeg_bytes = pixel_array_8bit.tobytes()
        ffmpeg_pix_fmt_in = "gray"  # Now input to FFmpeg is 8-bit grayscale
        print(
            f"Debug: Converted to 8-bit gray. New min/max for FFmpeg input: {pixel_array_8bit.min()}/{pixel_array_8bit.max()}"
        )
    elif ds.BitsAllocated == 8:
        ffmpeg_pix_fmt_in = "gray"
        pixel_array_for_ffmpeg_bytes = pixel_array_for_processing.astype(np.uint8).tobytes()
    else:
        # This part was already there
        print(
            f"Unsupported BitsAllocated: {ds.BitsAllocated} in {input_dicom_path}. Only 8 or 16 bit (now converted to 8) supported."
        )
        return

    print(
        f"Debug: Final ffmpeg_pix_fmt_in selected: {ffmpeg_pix_fmt_in}"
    )  # Should now always be 'gray' if 16-bit path taken

    # ... after pixel_array_for_processing is finalized ...
    print(f"Debug: ds.PhotometricInterpretation: {ds.PhotometricInterpretation}")
    print(f"Debug: ds.BitsAllocated: {ds.BitsAllocated}, ds.BitsStored: {ds.BitsStored}")
    print(f"Debug: pixel_array_for_processing.dtype: {pixel_array_for_processing.dtype}")
    print(f"Debug: pixel_array_for_processing.shape: {pixel_array_for_processing.shape}")
    if num_frames > 0:
        print(
            f"Debug: pixel_array_for_processing min/max: {pixel_array_for_processing.min()}/{pixel_array_for_processing.max()}"
        )
    print(f"Debug: ffmpeg_pix_fmt_in selected: {ffmpeg_pix_fmt_in}")
    print(f"Debug: num_frames: {num_frames}, input_rows: {input_rows}, input_cols: {input_cols}")

    effective_output_width = output_width
    effective_output_height = output_height

    if output_width % 2 != 0:
        effective_output_width = output_width - 1
        print(
            f"Warning: Output width {output_width} is odd; H.264 with yuv420p requires even dimensions. Adjusting to {effective_output_width}."
        )
    if output_height % 2 != 0:
        effective_output_height = output_height - 1
        print(
            f"Warning: Output height {output_height} is odd; H.264 with yuv420p requires even dimensions. Adjusting to {effective_output_height}."
        )

    if effective_output_width <= 0 or effective_output_height <= 0:
        print(
            f"Error: Output dimensions ({effective_output_width}x{effective_output_height}) are invalid after MOD2 adjustment."
        )
        return

    print("Starting FFmpeg transcoding to H.264...")
    print(f"Input: {num_frames} frames, {input_cols}x{input_rows}, pix_fmt_in: {ffmpeg_pix_fmt_in}")
    print(f"Output: {output_width}x{output_height}, 10 fps, CRF: {crf_value}, pix_fmt_out: yuv420p")

    # vf_chain should still be:
    # vf_chain = f"scale={effective_output_width}:{effective_output_height}:in_range=pc:out_range=tv,format=yuv420p"
    # or, if you suspected in_range/out_range were problematic, a simpler one:
    # vf_chain = f"scale={effective_output_width}:{effective_output_height},format=yuv420p"
    # print(f"Debug: Using vf_chain for MP4 output: {vf_chain}")
    temp_mp4_file = "temp_ffmpeg_output.mp4"  # Define temp MP4 filename
    if os.path.exists(temp_mp4_file):
        os.remove(temp_mp4_file)

    print(f"Starting FFmpeg transcoding (writing directly to {temp_mp4_file})...")
    # Note: Input print statements refer to what's piped to FFmpeg
    print(f"Input to FFmpeg: {num_frames} frames, {input_cols}x{input_rows}, pix_fmt_in: {ffmpeg_pix_fmt_in}")
    print(f"Target MP4 output: {effective_output_width}x{effective_output_height}, 10 fps, CRF: {crf_value}")

    try:
        process = (
            ffmpeg.input(
                "pipe:",
                format="rawvideo",
                pix_fmt=ffmpeg_pix_fmt_in,  # This is 'gray'
                s=f"{input_cols}x{input_rows}",
                framerate="10",
            )
            .output(
                temp_mp4_file,  # FFmpeg outputs to this filename
                format="mp4",
                vcodec="libx264",
                pix_fmt="yuv420p",
                s=f"{effective_output_width}x{effective_output_height}",
                r=10,
                crf=crf_value,
                preset="medium",
                movflags="+faststart",  # Try direct kwarg for -movflags +faststart
            )
            .global_args("-hide_banner", "-loglevel", "warning")
            .run_async(pipe_stdin=True, pipe_stderr=True)  # No pipe_stdout for this step
        )

        # Feed the 8-bit grayscale pixel data
        _, stderr_data = process.communicate(input=pixel_array_for_ffmpeg_bytes)

        if stderr_data:
            decoded_stderr = stderr_data.decode("utf-8", errors="ignore").strip()
            if decoded_stderr or process.returncode != 0:
                print(f"FFmpeg stderr output (writing {temp_mp4_file}):\n{decoded_stderr}")

        if process.returncode != 0:
            print(f"FFmpeg Error (return code {process.returncode}) while writing {temp_mp4_file}.")
            return  # Stop if MP4 creation failed

        if not os.path.exists(temp_mp4_file) or os.path.getsize(temp_mp4_file) == 0:
            print(f"FFmpeg produced an empty or missing MP4 file: {temp_mp4_file}.")
            return  # Stop if MP4 is invalid

        print(f"FFmpeg successfully created intermediate MP4 file: {temp_mp4_file}")

        # Now, read the bytes from this newly created MP4 file
        video_bytestream_for_dicom = None
        with open(temp_mp4_file, "rb") as f_mp4:
            video_bytestream_for_dicom = f_mp4.read()
        print(
            f"Successfully read {len(video_bytestream_for_dicom)} bytes from {temp_mp4_file} for DICOM encapsulation."
        )

        # Clean up the temporary MP4 file (optional, or do it at the end)
        # if os.path.exists(temp_mp4_file):
        #     os.remove(temp_mp4_file)

    except ffmpeg.Error as e:
        print(f"ffmpeg-python error (writing {temp_mp4_file}): {e}")
        if hasattr(e, "stderr") and e.stderr:
            print(f"FFmpeg stderr (from exception):\n{e.stderr.decode('utf-8', errors='ignore')}")
        return
    except Exception as e:
        print(f"An unexpected error occurred during FFmpeg processing for {temp_mp4_file}: {e}")
        return

    # debug_mp4_output_path = "debug_ffmpeg_output.mp4"
    # if os.path.exists(debug_mp4_output_path):
    #     os.remove(debug_mp4_output_path)

    # print("Starting FFmpeg transcoding (Piping H.264 stream, simplest conversion)...")
    # # NO explicit vf_chain. Let FFmpeg auto-insert filters for scaling and gray -> yuv420p.

    # try:
    #     process = (
    #         ffmpeg.input(
    #             "pipe:",
    #             format="rawvideo",
    #             pix_fmt=ffmpeg_pix_fmt_in,  # This will be 'gray'
    #             s=f"{input_cols}x{input_rows}",
    #             framerate="10",
    #         )
    #         .output(
    #             "pipe:",  # Outputting raw H.264 stream to stdout
    #             format="h264",  # Request raw H.264 elementary stream (Annex B)
    #             vcodec="libx264",
    #             pix_fmt="yuv420p",  # Request yuv420p for the output. FFmpeg will scale and convert.
    #             s=f"{effective_output_width}x{effective_output_height}",  # Explicitly request output size
    #             r=10,
    #             crf=crf_value,
    #             preset="medium",
    #             profile="high",
    #             level="4.1",
    #         )
    #         .global_args("-hide_banner", "-loglevel", "warning")
    #         .run_async(pipe_stdin=True, pipe_stdout=True, pipe_stderr=True)
    #     )

    #     # Feed the 8-bit grayscale data (already prepared in pixel_array_for_ffmpeg_bytes)
    #     h264_bitstream_bytes, stderr_data = process.communicate(input=pixel_array_for_ffmpeg_bytes)

    #     # It's still good to print stderr_data if it exists, even with -loglevel error,
    #     # as actual errors will still be printed.
    #     if stderr_data:
    #         # Only print if there's substantial content, or if returncode is non-zero
    #         # For now, let's print it if it's not empty, to catch any brief messages.
    #         try:
    #             decoded_stderr = stderr_data.decode("utf-8", errors="ignore").strip()
    #             if decoded_stderr:  # Print only if there's actual content after stripping
    #                 print(f"FFmpeg stderr output (H.264 pipe with loglevel error):\n{decoded_stderr}")
    #         except:  # Fallback if decoding fails for some reason
    #             if stderr_data:
    #                 print("FFmpeg stderr output (H.264 pipe, raw bytes):\n", stderr_data)

    #     if process.returncode != 0:
    #         print(f"FFmpeg Error (return code {process.returncode}) during H.264 pipe for {input_dicom_path}.")
    #         # stderr would have been printed above
    #         return

    #     # This is where the script currently fails
    #     if not h264_bitstream_bytes:
    #         print(f"FFmpeg produced an empty H.264 bitstream via pipe for {input_dicom_path}.")
    #         print(f"Return code was: {process.returncode}")  # Add this for more info
    #         # If stderr_data was empty before, print it now for sure if bitstream is empty
    #         if not (stderr_data and stderr_data.decode("utf-8", errors="ignore").strip()):
    #             print(f"FFmpeg stderr (in case it was missed, raw): {stderr_data}")
    #         return

    #     print(
    #         f"FFmpeg H.264 pipe successful for {input_dicom_path}. Bitstream size: {len(h264_bitstream_bytes)} bytes."
    #     )

    #     # Save the raw H.264 bitstream received by Python to a file for inspection
    #     raw_h264_output_path = "debug_piped_stream.h264"
    #     try:
    #         with open(raw_h264_output_path, "wb") as f_h264:
    #             f_h264.write(h264_bitstream_bytes)
    #         print(f"Saved piped H.264 bitstream to: {raw_h264_output_path}")
    #         print(f"Try playing it with: ffplay -f h264 -i {raw_h264_output_path}")
    #         print(f"Or convert to MP4: ffmpeg -framerate 10 -i {raw_h264_output_path} -c copy debug_piped_stream.mp4")
    #     except Exception as e_write:
    #         print(f"Error writing debug_piped_stream.h264: {e_write}")
    #     # --- END OF THE ONE RECOMMENDED CHANGE ---

    #     # if not os.path.exists(debug_mp4_output_path) or os.path.getsize(debug_mp4_output_path) == 0:
    #     #     print(f"FFmpeg still produced an empty or missing MP4 file: {debug_mp4_output_path}.")
    #     #     return

    #     # print(f"FFmpeg MP4 debug file created: {debug_mp4_output_path}. Please check this file visually.")
    #     # print("Further DICOM encapsulation will be skipped for this debug run.")
    #     # return

    # except ffmpeg.Error as e:
    #     print(f"ffmpeg-python error (MP4 debug) for {input_dicom_path}: {e}")
    #     if hasattr(e, "stderr") and e.stderr:
    #         print(f"FFmpeg stderr (from exception):\n{e.stderr.decode('utf-8', errors='ignore')}")
    #     return
    # except Exception as e:
    #     print(f"An unexpected error occurred during FFmpeg MP4 debug processing of {input_dicom_path}: {e}")
    #     return

    # 4. Re-encapsulate into DICOM using deepcopy and modification
    print(f"Re-encapsulating H.264 bitstream into DICOM for {input_dicom_path}...")

    out_ds = copy.deepcopy(ds)  # Deep copy the original dataset

    # --- Update File Meta Information ---
    new_sop_instance_uid = generate_uid()  # Generate new SOP Instance UID once
    out_ds.file_meta.MediaStorageSOPInstanceUID = new_sop_instance_uid
    out_ds.file_meta.TransferSyntaxUID = UID("1.2.840.10008.1.2.4.102")  # H.264 High Profile / Level 4.1
    # --- CRITICAL DICOM IDENTITY ---
    video_sop_class_uid = UID("1.2.840.10008.5.1.4.1.1.77.1.4.1")  # Video Photographic Image Storage
    out_ds.file_meta.MediaStorageSOPClassUID = video_sop_class_uid
    out_ds.file_meta.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID
    out_ds.file_meta.ImplementationVersionName = f"PYDICOM {pydicom.__version__}"
    # MediaStorageSOPClassUID is copied from ds.SOPClassUID by deepcopy, which is fine if we keep it.
    # If changing SOPClassUID below, ensure file_meta.MediaStorageSOPClassUID matches.

    # Inside transcode_dicom_to_h264_dicom, after new_sop_instance_uid, new_series_instance_uid

    # --- START OF THE ONE RECOMMENDED SET OF CHANGES (Fuller Metadata Alignment) ---
    # Create a new FileDataset from scratch
    file_meta = FileMetaDataset()
    # Pass the intended output filename to the FileDataset constructor
    out_ds = FileDataset(output_dicom_path, {}, file_meta=file_meta, preamble=b"\0" * 128)

    # 1. Populate File Meta Information
    video_sop_class_uid = UID("1.2.840.10008.5.1.4.1.1.77.1.4.1")  # Video Photographic Image Storage
    # new_sop_instance_uid is already generated

    out_ds.file_meta.MediaStorageSOPClassUID = video_sop_class_uid
    out_ds.file_meta.MediaStorageSOPInstanceUID = new_sop_instance_uid
    out_ds.file_meta.TransferSyntaxUID = UID("1.2.840.10008.1.2.4.102")
    out_ds.file_meta.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID
    out_ds.file_meta.ImplementationVersionName = f"PYDICOM {pydicom.__version__}"

    # 2. Populate Main Dataset (mirroring test_720.dcm structure more closely)
    out_ds.SOPClassUID = video_sop_class_uid
    out_ds.SOPInstanceUID = new_sop_instance_uid

    # Try to carry over original StudyInstanceUID if 'ds' is available, else generate new
    original_ds = ds  # Assuming 'ds' is the input dataset
    out_ds.StudyInstanceUID = (
        original_ds.StudyInstanceUID if "StudyInstanceUID" in original_ds else generate_uid(prefix="1.3.51.0.7.")
    )  # Example prefix
    out_ds.SeriesInstanceUID = generate_uid(prefix="1.3.51.5146.11682.")

    # Patient Module Attributes (Type 2 in Video Photographic Image Storage IOD)
    out_ds.PatientName = original_ds.PatientName if "PatientName" in original_ds else "Anonymous^Patient"
    out_ds.PatientID = original_ds.PatientID if "PatientID" in original_ds else "UNKNOWN_PID"
    out_ds.PatientBirthDate = original_ds.PatientBirthDate if "PatientBirthDate" in original_ds else "19000101"  # Dummy
    out_ds.PatientSex = original_ds.PatientSex if "PatientSex" in original_ds else "O"  # Dummy 'Other'

    # General Study Module Attributes (Type 2)
    from datetime import datetime  # Ensure datetime is imported

    now = datetime.now()
    current_date = now.strftime("%Y%m%d")
    current_time = now.strftime("%H%M%S.%f")[:13]

    out_ds.StudyDate = original_ds.StudyDate if "StudyDate" in original_ds else current_date
    out_ds.StudyTime = (
        original_ds.StudyTime if "StudyTime" in original_ds else current_time[:6]
    )  # TM VR typically up to HHMMSS
    out_ds.AccessionNumber = original_ds.AccessionNumber if "AccessionNumber" in original_ds else "ACC001"  # Dummy
    out_ds.ReferringPhysicianName = (
        original_ds.ReferringPhysicianName if "ReferringPhysicianName" in original_ds else "Dr^AnonReferrer"
    )  # Dummy
    out_ds.StudyDescription = original_ds.StudyDescription if "StudyDescription" in original_ds else "H.264 Video"
    out_ds.StudyID = original_ds.StudyID if "StudyID" in original_ds else "STUDY001"

    # General Series Module Attributes
    out_ds.SeriesDate = original_ds.SeriesDate if "SeriesDate" in original_ds else current_date  # Type 3
    out_ds.SeriesTime = original_ds.SeriesTime if "SeriesTime" in original_ds else current_time[:6]  # Type 3
    out_ds.SeriesNumber = original_ds.SeriesNumber if "SeriesNumber" in original_ds else "1"  # Type 2
    out_ds.SeriesDescription = (
        original_ds.SeriesDescription if "SeriesDescription" in original_ds else "H.264 Series from XA"
    )

    out_ds.Modality = "XC"
    out_ds.Manufacturer = "FFmpegPyDICOM_Script_V4"  # Increment version for tracking

    # General Image Module Attributes
    out_ds.ImageType = ["DERIVED", "PRIMARY"]  # Type 1
    out_ds.InstanceCreationDate = current_date  # Type 3
    out_ds.InstanceCreationTime = current_time  # Type 3
    out_ds.InstanceNumber = "1"  # Type 2
    # PatientOrientation (0020,0020) is Type 2C, test_720.dcm had (no value). We can omit or set empty.
    out_ds.PatientOrientation = ""  # Set empty as per test_720.dcm having "no value"

    # Cine Module (test_720.dcm had CineRate)
    # FrameTime is Type 1 in Video IODs if CineRate is not used to derive it.
    # RecommendedDisplayFrameRate is Type 3.
    # test_720.dcm had CineRate and FrameTime, but not RecommendedDisplayFrameRate.
    out_ds.FrameTime = str(round(1000 / 10, 2))  # 100.0 for 10fps
    out_ds.CineRate = str(10)  # IS (Integer String), matches our 10fps
    if "RecommendedDisplayFrameRate" in out_ds:  # Omit this to match test_720.dcm
        del out_ds.RecommendedDisplayFrameRate

    # VL Image Module
    out_ds.AcquisitionDate = current_date  # Type 2 (can be same as instance creation)
    out_ds.AcquisitionTime = current_time  # Type 2
    out_ds.AcquisitionContextSequence = []  # Type 2, add as empty to match test_720.dcm

    if "SpecificCharacterSet" in original_ds and original_ds.SpecificCharacterSet:
        out_ds.SpecificCharacterSet = original_ds.SpecificCharacterSet
    else:
        out_ds.SpecificCharacterSet = "ISO_IR 100"

    # Pixel Data Description (should be correct from previous steps)
    out_ds.PhotometricInterpretation = "YBR_PARTIAL_420"
    out_ds.SamplesPerPixel = 3
    out_ds.PlanarConfiguration = 0
    out_ds.Rows = effective_output_height
    out_ds.Columns = effective_output_width
    out_ds.BitsAllocated = 8
    out_ds.BitsStored = 8
    out_ds.HighBit = 7
    out_ds.PixelRepresentation = 0

    # Frame Information (should be correct)
    out_ds.NumberOfFrames = num_frames
    out_ds.FrameIncrementPointer = (0x0018, 0x1063)

    # Lossy Compression Attributes
    out_ds.LossyImageCompression = "01"  # Type 1
    # OMIT LossyImageCompressionMethod (Type 3) and Ratio (Type 3) to match test_720.dcm
    if "LossyImageCompressionMethod" in out_ds:
        del out_ds.LossyImageCompressionMethod
    if "LossyImageCompressionRatio" in out_ds:
        del out_ds.LossyImageCompressionRatio

    # Pixel Data Encapsulation
    if video_bytestream_for_dicom:  # This variable now holds the MP4 file bytes
        out_ds.PixelData = encapsulate([video_bytestream_for_dicom])
    else:
        print("Error: MP4 bytestream (from file) is empty before DICOM encapsulation.")
        return

    # Pixel Data Encapsulation
    # if h264_bitstream_bytes:
    #     out_ds.PixelData = encapsulate([h264_bitstream_bytes])
    # else:
    #     print("Error: H.264 bitstream is empty before DICOM encapsulation.")
    #     return

    out_ds[0x7FE00010].VR = "OB"

    out_ds.is_little_endian = True
    out_ds.is_implicit_VR = False
    # --- END OF THE ONE RECOMMENDED SET OF CHANGES ---

    # 5. Write Output DICOM File
    try:
        # output_dicom_path was passed to FileDataset constructor by ds.copy() if ds.filename was set
        # but dcmwrite will use the path given to it.
        pydicom.dcmwrite(output_dicom_path, out_ds, write_like_original=False)
        print(f"Successfully created H.264 DICOM: {output_dicom_path}")
    except Exception as e:
        print(f"Error writing output DICOM file {output_dicom_path}: {e}")


def create_dummy_xa_dcm():
    print(f"Creating a dummy DICOM file: {dummy_input_filename} for testing...")

    file_meta_dummy = FileMetaDataset()
    file_meta_dummy.MediaStorageSOPClassUID = UID("1.2.840.10008.5.1.4.1.1.12.1")  # XA Storage
    file_meta_dummy.MediaStorageSOPInstanceUID = generate_uid()
    file_meta_dummy.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID
    file_meta_dummy.ImplementationVersionName = f"PYDICOM {pydicom.__version__}"
    file_meta_dummy.TransferSyntaxUID = ExplicitVRLittleEndian

    ds_dummy = FileDataset(dummy_input_filename, {}, file_meta=file_meta_dummy, preamble=b"\0" * 128)

    ds_dummy.SOPClassUID = file_meta_dummy.MediaStorageSOPClassUID
    ds_dummy.SOPInstanceUID = file_meta_dummy.MediaStorageSOPInstanceUID
    ds_dummy.PatientName = "Test^Patient"
    ds_dummy.PatientID = "123456_12BITSIM"
    ds_dummy.Modality = "XA"
    ds_dummy.StudyInstanceUID = generate_uid()
    ds_dummy.SeriesInstanceUID = generate_uid()
    ds_dummy.SpecificCharacterSet = "ISO_IR 100"

    ds_dummy.SamplesPerPixel = 1
    ds_dummy.PhotometricInterpretation = "MONOCHROME2"
    ds_dummy.Rows = 128  # Dummy input rows
    ds_dummy.Columns = 128  # Dummy input columns
    ds_dummy.BitsAllocated = 16
    ds_dummy.BitsStored = 12
    ds_dummy.HighBit = 11
    ds_dummy.PixelRepresentation = 0

    num_test_frames = 30
    # test_pixel_data = np.zeros((num_test_frames, ds_dummy.Rows, ds_dummy.Columns), dtype=np.uint8)
    # for i in range(num_test_frames):
    #     val_col = int((i / num_test_frames) * ds_dummy.Columns)
    #     val_intensity = int((i / num_test_frames) * 100) + 50
    #     frame = np.full((ds_dummy.Rows, ds_dummy.Columns), 100, dtype=np.uint8)
    #     frame[:, max(0, val_col - 5) : min(ds_dummy.Columns, val_col + 5)] = val_intensity
    #     test_pixel_data[i, :, :] = frame

    # ds_dummy.NumberOfFrames = num_test_frames
    # ds_dummy.PixelData = test_pixel_data.tobytes()
    test_pixel_data_16bit = np.zeros((num_test_frames, ds_dummy.Rows, ds_dummy.Columns), dtype=np.uint16)
    for i in range(num_test_frames):
        col_pos = int((i / num_test_frames) * ds_dummy.Columns)
        # Intensity sweep within a significant portion of the 12-bit range (0-4095)
        intensity = int((i / num_test_frames) * 3500) + 200  # e.g., sweeps from 200 to 3700

        frame = np.full((ds_dummy.Rows, ds_dummy.Columns), intensity // 3, dtype=np.uint16)
        stripe_start = max(0, col_pos - 7)
        stripe_end = min(ds_dummy.Columns, col_pos + 7)
        frame[:, stripe_start:stripe_end] = intensity

        # Ensure values are clipped to the 12-bit maximum (4095)
        # Pydicom's ds.pixel_array would return values in this 0-4095 range for such a DICOM.
        test_pixel_data_16bit[i, :, :] = np.clip(frame, 0, 4095)

    ds_dummy.NumberOfFrames = num_test_frames  # This should already be there or set with num_test_frames
    ds_dummy.PixelData = test_pixel_data_16bit.tobytes()

    ds_dummy.is_little_endian = True
    ds_dummy.is_implicit_VR = False

    pydicom.dcmwrite(dummy_input_filename, ds_dummy)
    print(f"Dummy DICOM file created successfully: {dummy_input_filename}")


# --- Example Usage (slightly modified dummy creation for clarity) ---
if __name__ == "__main__":
    dummy_input_filename = "test_uncompressed_xa_input.dcm"
    dummy_output_filename = "test_transcoded_video.mp4.dcm"

    if os.path.exists(dummy_input_filename):
        os.remove(dummy_input_filename)
    if os.path.exists(dummy_output_filename):
        os.remove(dummy_output_filename)

    try:
        create_dummy_xa_dcm()

        # Corrected example call:
        # transcode_dicom_to_h264_dicom(
        #     input_dicom_path=dummy_input_filename,
        #     output_dicom_path=dummy_output_filename,
        #     output_width=128,  # Output width, same as dummy input for this example
        #     output_height=128,  # Output height, same as dummy input for this example
        #     crf_value=28,
        # )

        transcode_dicom_to_h264_dicom(
            input_dicom_path="xa_test.dcm",
            output_dicom_path="xa_test.mp4.dcm",
            output_width=750,  # Output width, same as dummy input for this example
            output_height=750,  # Output height, same as dummy input for this example
            crf_value=17,
        )

    except ImportError as e:
        print(f"A required library is not installed: {e}. Please install pydicom, ffmpeg-python, and numpy.")
    except FileNotFoundError:
        print("FFmpeg executable not found. Please ensure FFmpeg is installed and in your system's PATH.")
    except Exception as e:
        print(f"An error occurred in the example usage: {e}")
        import traceback

        traceback.print_exc()
