# RadLex and harmonized CT series descriptions (historical FALCON notes)

Product Harmonize now uses **TotalSegmentator + RSNA Playbook / LOINC** only. FALCON is retained under `src/prototyping/falcon/` for offline research; it is not used by Series View or AI Batch.

This note keeps terminology context that once guided the FALCON RadLex-style formatter in `predict._format_radlex_series_description()`.

## What product Harmonize produces today

Playbook+ multi-region syntax (from `controller/ai/harmonize` + tseg regions):

```text
{Modality} {Body regions joined by +} {With Contrast | Without Contrast}
```

Examples:

- `CT Chest With Contrast`
- `CT Head+Neck Without Contrast`
- `CT Chest+Abdomen With Contrast`

## Historical FALCON formatter (prototyping)

When FALCON was used as a fallback, descriptions looked like:

```text
CT {Head Neck | Chest | Abdomen} {With Contrast | Without Contrast}
```

`HeadNeck` was spaced as `Head Neck` (not Playbook+ `Head+Neck`).

## External sources

- RSNA Radiology Playbook / LOINC study names — see product Harmonize docs and `playbook.py`
- Upstream FALCON publication — see [README.md](README.md)
