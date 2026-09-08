# Planar Harmonize (XR / US / MG)

Metadata-only Harmonize for **CR/DX (XR)**, **US**, and **MG**. Isolated from the CT/MR TotalSegmentator path in `playbook.py` / `modality_profile.py`.

| Cohort | App modalities | Series string examples | LOINC prefix |
| --- | --- | --- | --- |
| XR | CR, DX | `Chest AP` | `XR ` |
| US | US | `Abdomen`, `Doppler Carotid` | `US ` / `US.doppler ` |
| MG | MG | `Breast L MLO` | `MG ` / `DBT ` / `FFD ` |

**Ignored:** SC, OT, DOC, PT, NM, RF, etc.

**Isolation:** `harmonize_series` dispatches CT/MR to `_harmonize_series_tseg` and planar modalities to `_harmonize_one_planar_series`. Planar never calls TotalSegmentator. Mixed CT+DX studies still gate LOINC on CT/MR completion only.
