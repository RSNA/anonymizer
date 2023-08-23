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

cr1_filename = CR_STUDY_3_SERIES_3_IMAGES[0]
# cr1_SOPInstanceUID = "1.3.6.1.4.1.5962.1.1.0.0.0.1196527414.5534.0.11"
# cr1_StudyInstanceUID = "1.3.6.1.4.1.5962.1.1.0.0.0.1196527414.5534.0.1"
# cr1_SeriesInstanceUID = "1.3.6.1.4.1.5962.1.1.0.0.0.1196527414.5534.0.10"
# cr1_patient_name = "Doe^Archibald"
# cr1_patient_id = "77654033"

ct_small_filename = "CT_small.dcm"
# ct_small_SOPInstanceUID = "1.3.6.1.4.1.5962.1.1.1.1.1.20040119072730.12322"
# ct_small_StudyInstanceUID = "1.3.6.1.4.1.5962.1.2.1.20040119072730.12322"
# ct_small_SeriesInstanceUID = "1.3.6.1.4.1.5962.1.3.1.1.20040119072730.12322"
# ct_small_patient_name = "CompressedSamples^CT1"
# ct_small_patient_id = "1CT1"

mr_small_filename = "MR_small.dcm"
# mr_small_StudyInstanceUID = "1.3.6.1.4.1.5962.1.2.4.20040826185059.5457"
# mr_small_SeriesInstanceUID = "1.3.6.1.4.1.5962.1.3.4.1.20040826185059.5457"
# mr_small_patient_name = "CompressedSamples^MR1"
# mr_small_patient_id = "4MR1"
