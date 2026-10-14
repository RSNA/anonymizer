# Pseudo-PHI de-id experiment

## Goal

Use **rsna-anonymizer core** + **EasyOCR** + **OpenMed** to de-identify Pseudo-PHI Evaluation files so candidates match DeIdentified gold at **>95% accuracy**. **UIDs need not match.** Clinical script may be adapted under `scripts/` with general DICOM rules only.

## Accuracy (plain English)

Comparable checks = non-UID headers + pixel rule + overlay presence. Cohort accuracy = matches / comparable (micro-average). Pass if **>95%**.

- Headers: candidate value equals gold (normalized text).
- Pixels: if eval==gold, do not invent redaction; if they differ, clean toward gold.
- Overlays: match gold presence/absence (gold clears PT 60xx overlays).
- Excluded: UIDs, file-meta transfer syntax, anonymizer stamp tags.

## Phases

0. Characterize → 1. Baselines → 2. Taxonomy (+ script patches) → 3. Pixels → 4. Freeze + `results/FINAL_REPORT.md`

## Result (frozen)

Cohort accuracy **97.636%** on 1691 pairs (**PASS** vs >95%). Winning recipe: OpenMed blank + PS3.15 PHI keyword empty + minimal identity/date remap + overlay strip + EasyOCR on the 5 burn-in-positive SOPs. Full stock clinical script alone scored ~48% (over-removes coded sequences).

## Dataset

Evaluation / DeIdentified under `/Users/michaelevans/DATA/Pseudo-PHI-DICOM-Dataset/…`. Pair by UID crosswalk only. Do not gate on `BurnedInAnnotation`.
