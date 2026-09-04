# De-identification protocol

This page summarizes how the Anonymizer follows the DICOM Basic Application Confidentiality Profile ([PS 3.15 Appendix E](https://dicom.nema.org/medical/dicom/2023b/output/chtml/part15/chapter_E.html)) in plain language.

## What gets removed or replaced

- Patient name and ID become project-scoped anonymized values (Site ID + sequential patient number). The same person keeps the same anonymized ID across studies in the project.
- UIDs are replaced with new values derived for the project (hashed from originals in current versions) so links between images stay consistent without exposing source UIDs.
- Many clinical workflow and private tags are removed.
- The file records that patient identity was removed and names the RSNA DICOM Anonymizer as the method.

## Dates

Dates are shifted per patient (hash-based offset) so the **order and spacing** of a patient’s studies stay meaningful, but calendar dates are not the originals. Time-of-day is typically left as-is.

## What may be kept (partial options)

Examples of retained clinical context (depending on script / profile options):

- Study and Series descriptions (you may later standardize series names with Harmonize)
- Sex, age, size, weight, and similar characteristics when configured
- Manufacturer / model when configured

## Pixel and face options in the DICOM profile

The classic profile options “clean pixel data” and “clean recognizable visual features” are **not** claimed as automatic DICOM profile bits alone. In V19, use optional AI Features instead:

- [Remove burned-in text](07-process/02-remove-burned-in-text)
- [Blur faces](07-process/04-blur-faces)

## Structured reports and overlays

Curve/overlay groups are removed. Whether Structured Report objects are accepted is controlled by project storage-class settings.

!!! note "For compliance review"
    Have your privacy officer review the anonymizer script and AI tools for your institution. This manual is operational guidance, not legal advice.
