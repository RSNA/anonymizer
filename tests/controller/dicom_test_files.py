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
hash_ct_doe_archibald_StudyInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.11340611439380947926269341130"
hash_ct_doe_archibald_SeriesInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.87089945604807972202353046051"
hash_ct_doe_archibald_SOPInstanceUID1 = "1.2.826.0.1.3680043.10.474.99.99.2.16357731307136892687833192242"

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

# CR Study Multiple Series, Multiple Images
patient1_name = "Doe^Archibald"
patient1_id = "77654033"
cr1_filename = CR_STUDY_3_SERIES_3_IMAGES[0]
cr1_SOPInstanceUID = "1.3.6.1.4.1.5962.1.1.0.0.0.1196527414.5534.0.11"
hash_cr1_SOPInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.59126730574505290677259995400"
cr1_StudyInstanceUID = "1.3.6.1.4.1.5962.1.1.0.0.0.1196527414.5534.0.1"
hash_cr1_StudyInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.9731451180799172874182059247"
cr1_SeriesInstanceUID = "1.3.6.1.4.1.5962.1.1.0.0.0.1196527414.5534.0.10"
hash_cr1_SeriesInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.1846002009586697489540184747"

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
hash_ct_small_StudyInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.6717804446222440140472768993"
ct_small_SeriesInstanceUID = "1.3.6.1.4.1.5962.1.3.1.1.20040119072730.12322"
hash_ct_small_SeriesInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.16606532314764800133004562388"
ct_small_SOPInstanceUID = "1.3.6.1.4.1.5962.1.1.1.1.1.20040119072730.12322"
hash_ct_small_SOPInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.62260353221523252971326212871"
hash_ct_small_FrameOfReferenceUID = "1.2.826.0.1.3680043.10.474.99.99.2.52429401742996609447809236145"

# MR image, Explicit VR, LittleEndian:
patient4_name = "CompressedSamples^MR1"
patient4_id = "4MR1"
mr_small_filename = "MR_small.dcm"
mr_small_StudyInstanceUID = "1.3.6.1.4.1.5962.1.2.4.20040826185059.5457"
hash_mr_small_StudyInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.85147041362592413610973152908"
mr_small_SeriesInstanceUID = "1.3.6.1.4.1.5962.1.3.4.1.20040826185059.5457"
hash_mr_small_SeriesInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.14054801912608031741135888775"
hash_mr_small_SOPInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.4262856288650438136088168979"
hash_mr_small_FrameOfReferenceUID = "1.2.826.0.1.3680043.10.474.99.99.2.57357603303793793153345859616"
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
hash_jpeg_baseline_StudyInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.83843521336952889895330813189"
hash_jpeg_baseline_SeriesInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.82845524358746261914140506388"
hash_jpeg_baseline_SOPInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.63173687280773373407015697496"

hash_jpeg_extended_StudyInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.53193122984843516890131883749"
hash_jpeg_extended_SeriesInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.79779764707105881991254591984"
hash_jpeg_extended_SOPInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.31992309565814706496071602240"

hash_jpeg_lossless_p14_StudyInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.53193122984843516890131883749"
hash_jpeg_lossless_p14_SeriesInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.79779764707105881991254591984"
hash_jpeg_lossless_p14_SOPInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.68661932533073478738258685821"

hash_jpeg_ls_lossless_StudyInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.85147041362592413610973152908"
hash_jpeg_ls_lossless_SeriesInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.14054801912608031741135888775"
hash_jpeg_ls_lossless_SOPInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.4262856288650438136088168979"

hash_jpeg_ls_lossy_StudyInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.15779118267283544512875719022"
hash_jpeg_ls_lossy_SeriesInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.62374790530173830700466557799"
hash_jpeg_ls_lossy_SOPInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.63582736419007703949921092757"

hash_jpeg_2000_lossless_StudyInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.85147041362592413610973152908"
hash_jpeg_2000_lossless_SeriesInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.14054801912608031741135888775"
hash_jpeg_2000_lossless_SOPInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.4262856288650438136088168979"

hash_jpeg_2000_StudyInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.53193122984843516890131883749"
hash_jpeg_2000_SeriesInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.79779764707105881991254591984"
hash_jpeg_2000_SOPInstanceUID = "1.2.826.0.1.3680043.10.474.99.99.2.42877986442930554750347098660"

