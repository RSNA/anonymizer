# FALCON integration (RSNA Anonymizer)

This directory documents how the RSNA Anonymizer embeds **FALCON** (Fully Automated Labeling of CT anatomy and intravenous CONtrast) for CT series metadata assistance. The implementation lives in the parent package: `src/anonymizer/controller/falcon/`.

FALCON predicts **body part** (Head/Neck, Chest, Abdomen) and **IV contrast** from CT pixel data. Series View **Harmonize Description** uses those predictions to propose a RadLex-style **Series Description** `(0008,103E)`. See [RadLex_Notes.md](RadLex_Notes.md) for terminology sources and naming limits.

---

## Upstream FALCON project

| Item | Detail |
| ---- | ------ |
| Repository | [https://github.com/FintelmannLabDevelopmentTeam/Falcon](https://github.com/FintelmannLabDevelopmentTeam/Falcon) |
| Description | Fully-automated labeling of CT anatomy and IV contrast |
| Developer | Philipp Kaess, Fintelmann Lab, Massachusetts General Hospital, Boston, MA |
| License (upstream) | MIT License, Copyright (c) 2024 Philipp Kaess |

### Pinned model weights

Anonymizer downloads pretrained weights from a fixed upstream commit (see `load_models.FALCON_UPSTREAM_COMMIT`):

- Commit: `7c33595ff6f45e609b2b0a3f5168fec883b45f2c`
- Base URL: `https://raw.githubusercontent.com/FintelmannLabDevelopmentTeam/Falcon/7c33595ff6f45e609b2b0a3f5168fec883b45f2c/models/`

Local cache after download: `src/anonymizer/assets/falcon/models/` (resolved from the package root, independent of process cwd)

| File | Role |
| ---- | ---- |
| `body_part_model.pth` | Body part classification (3 classes) |
| `headneck_model.pth` | IV contrast, Head/Neck |
| `chest_model.pth` | IV contrast, Chest |
| `abdomen_model.pth` | IV contrast, Abdomen |

Models are loaded per inference batch in `predict.predict_falcon_series()` and released afterward (not kept in a global cache).

---

## Research publication

If you use FALCON functionality or report results derived from these models, cite the upstream publication:

**Title:** Open-Access Fully Automated Intravenous Contrast Detection and Body Part Classification for Computed Tomography Scans: The FALCON Model

**Journal:** Journal of Imaging Informatics in Medicine (Springer)

**DOI:** [https://doi.org/10.1007/s10278-026-01865-8](https://doi.org/10.1007/s10278-026-01865-8)

**Article:** [https://link.springer.com/article/10.1007/s10278-026-01865-8](https://link.springer.com/article/10.1007/s10278-026-01865-8)

**PubMed:** [https://pubmed.ncbi.nlm.nih.gov/41749033/](https://pubmed.ncbi.nlm.nih.gov/41749033/)

Recommended citation (from upstream README):

```text
Westphal, J.A., Kaess, P., Mantz, L. et al. Open-Access Fully Automated Intravenous
Contrast Detection and Body Part Classification for Computed Tomography Scans: The
FALCON Model. J Digit Imaging. Inform. med. (2026).
https://doi.org/10.1007/s10278-026-01865-8
```

---

## Architecture in this repository

| Module | Purpose |
| ------ | ------- |
| `predict.py` | Public API: `predict_falcon_series()`, `FalconPrediction`, RadLex-style description formatting |
| `load_models.py` | Download and load ResNet9 checkpoints |
| `resnet9.py` | ResNet9 network (vendored for inference) |
| `preprocessing/` | DICOM load, resample, crop to FALCON input volume |

**ResNet9:** Architecture adapted from FALCON / PrivateModelArchitectures 0.1.1 (see comment in `resnet9.py`).

**Scope of Anonymizer integration:** Inference and Harmonize UI only—not the standalone FALCON desktop GUI (`main.py` in the upstream repo). Preprocessing follows upstream expectations (`preprocess_series.py` constants: spacing, crop shape, HU clipping).

**UI entry point:** `src/anonymizer/view/series.py` — Harmonize Description (CT only).

**Startup:** `anonymizer.py` may call `ensure_falcon_models_downloaded()` so weights exist before Harmonize is used.

---

## Related documentation

- [FALCON_Evaluation.md](FALCON_Evaluation.md) — labeled manifest accuracy/F1 evaluation utility
- [RadLex_Notes.md](RadLex_Notes.md) — LOINC/RSNA Playbook, RadLex Series Playbook, and how proposed series descriptions relate to full Playbook compliance

---

## Acknowledgments

Body-part and IV-contrast models, training methodology, and primary tool development are credited to the Fintelmann Lab FALCON project and authors of the journal article above. RSNA Anonymizer integrates those models under the upstream MIT license for anonymized CT workflow support; RadLex-style naming in the app is a simplified local convention—see [RadLex_Notes.md](RadLex_Notes.md).
