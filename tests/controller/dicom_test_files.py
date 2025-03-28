# TEST FILES from pydicom/data/test_files
# see assets/docs/test files/pydicom_test_files.txt for details

# Doe^Archibald
CR_STUDY_3_SERIES_3_IMAGES = [
    "./77654033/CR1/6154",
    "./77654033/CR2/6247",
    "./77654033/CR3/6278",
]
# Doe^Archibald
CT_STUDY_1_SERIES_4_IMAGES = [
    "./77654033/CT2/17106",
    "./77654033/CT2/17136",
    "./77654033/CT2/17166",
    "./77654033/CT2/17196",
]

# Doe^Peter
MR_STUDY_3_SERIES_11_IMAGES = [
    "./98892003/MR1/5641",
    "./98892003/MR2/6935",
    "./98892003/MR2/6605",
    "./98892003/MR2/6273",
    "./98892003/MR700/4558",
    "./98892003/MR700/4528",
    "./98892003/MR700/4588",
    "./98892003/MR700/4467",
    "./98892003/MR700/4618",
    "./98892003/MR700/4678",
    "./98892003/MR700/4648",
]

# TODO: use @dataclass for TestDCMData


patient1_name = "Doe^Archibald"
patient1_id = "77654033"
cr1_filename = CR_STUDY_3_SERIES_3_IMAGES[0]
cr1_SOPInstanceUID = "1.3.6.1.4.1.5962.1.1.0.0.0.1196527414.5534.0.11"
cr1_StudyInstanceUID = "1.3.6.1.4.1.5962.1.1.0.0.0.1196527414.5534.0.1"
cr1_SeriesInstanceUID = "1.3.6.1.4.1.5962.1.1.0.0.0.1196527414.5534.0.10"

# Brain MRI 3 Series, 11 Images
patient2_name = "Doe^Peter"
patient2_id = "98890234"
mr_brain_StudyInstanceUID = "1.3.6.1.4.1.5962.1.1.0.0.0.1196533885.18148.0.1"
mr_brain_SeriesInstanceUID = "1.3.6.1.4.1.5962.1.1.0.0.0.1196533885.18148.0.1"
mr_brain_filename = MR_STUDY_3_SERIES_11_IMAGES[0]

# COMPRESSED Samples
patient3_name = "CompressedSamples^CT1"
patient3_id = "1CT1"
ct_small_filename = "CT_small.dcm"
ct_small_StudyInstanceUID = "1.3.6.1.4.1.5962.1.2.1.20040119072730.12322"
ct_small_SeriesInstanceUID = "1.3.6.1.4.1.5962.1.3.1.1.20040119072730.12322"
ct_small_SOPInstanceUID = "1.3.6.1.4.1.5962.1.1.1.1.1.20040119072730.12322"

# MR image, Explicit VR, LittleEndian:
patient4_name = "CompressedSamples^MR1"
patient4_id = "4MR1"
mr_small_filename = "MR_small.dcm"
mr_small_StudyInstanceUID = "1.3.6.1.4.1.5962.1.2.4.20040826185059.5457"
mr_small_SeriesInstanceUID = "1.3.6.1.4.1.5962.1.3.4.1.20040826185059.5457"

# MR_small.dcm image, Implicit VR, LittleEndian
mr_small_implicit_filename = "MR_small_implicit.dcm"
# MR_small.dcm image, Explicit VR, LittleEndian
mr_small_bigendian_filename = "MR_small_bigendian.dcm"

# Compressed Samples:
# if prefixed by test_files/, then the file is in the test_files directory else part of pydicom test files
COMPRESSED_TEST_FILES = {
    "JPEG_Baseline": "SC_jpeg_no_color_transform.dcm",  # ".50"      JPEG Baseline, Lossy, Non-Hierarchial
    "JPEG_Extended": "JPGExtended.dcm",  # ".51"                     JPEG Extended, Lossy, Non-Hierarchial
    #    "JPEG_Lossless_P14": "",                       # ".57"      JPEG Lossless Nonhierarchical (Processes 14).
    "JPEG_Lossless_P14_FOP": "JPEG-LL.dcm",  # ".70"                 JPEG Lossless Nonhierarchical, First-Order Prediction (Processes 14 [Selection Value 1])
    "JPEG-LS_Lossless": "MR_small_jpeg_ls_lossless.dcm",  # ".80"    JPEG-LS Lossless
    "JPEG-LS_Lossy": "test_dcm_files/JPEG-LS_Lossy.dcm",  # ".81",   JPEG-LS Lossy
    "JPEG2000_Lossless": "MR_small_jp2klossless.dcm",  # ".90"       JPEG 2000 Lossless
    "JPEG2000": "JPEG2000.dcm",  # ".91"                             JPEG 2000
}
