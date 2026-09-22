# Segment import test assets (real tool exports)

Curated samples under `tests/controller/assets/segment_imports/` for
tool-aware NIfTI/NRRD import tests. Prefer official public exports; see gaps below.

| Folder | Source | Contents |
| --- | --- | --- |
| `itk_snap/` | [ITK-SNAP MRI-crop tutorial](http://www.itksnap.org/download/snap/files/MRI-crop.zip) | `MRIcrop-seg.gipl` (original), `MRIcrop-seg.nii.gz` (SimpleITK conversion), `MRIcrop-seg.label` |
| `nnunet/` | [Medical Segmentation Decathlon Task04 Hippocampus](https://msd-for-monai.s3-us-west-2.amazonaws.com/Task04_Hippocampus.tar) | `labelsTr/hippocampus_001.nii.gz`, `dataset.json` (nnU-Net v2 name→int), `dataset_msd.json` (original MSD int→name) |
| `totalsegmentator/folder/` | [TotalSegmentator `tests/reference_files/example_seg_fast/`](https://github.com/wasserth/TotalSegmentator) | Binary masks: `liver`, `aorta`, `spleen`, `kidney_left`, `brain` |
| `totalsegmentator/ml/` | Same repo `example_seg_roi_subset.nii.gz` | Multi-label `--ml`-style volume + `class_map.json` (`5`→`liver`) |
| `slicer/` | **NRRD format sample** (see gap) | `example_labelmap.seg.nrrd` — voxels from TS `example_seg_roi_subset`, written as `.seg.nrrd` for NRRD/Slicer path coverage |
| `mitk/` | Same NRRD bytes as slicer sample | `labelmap.nrrd` — MITK-compatible labelmap container |

## Gaps (please source if you have them)

- **3D Slicer TinyPatient_Structures.seg.nrrd** — Slicer Sample Data (developer) hash `3243b62b…` is currently a stub (“Not Found”) on GitHub Releases. Drop the official file into `slicer/` and point tests at it when available.
- **MITK Workbench native export** — replace `mitk/labelmap.nrrd` with a file saved from MITK if you have one.
- **Full TotalSegmentator subject folder** — optional; five structures from `example_seg_fast` are enough for folder import.

## Licenses / attribution

- ITK-SNAP MRI-crop: ITK-SNAP tutorial data (PICSL / Yushkevich et al.).
- MSD Hippocampus: Medical Segmentation Decathlon.
- TotalSegmentator reference files: Wasserthal et al., Apache-2.0 project tests.
