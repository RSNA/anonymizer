# Troubleshooting

## Models and AI Features

| Message / symptom | What to try |
| --- | --- |
| Not ready / download failed | Return to **Welcome**, open **AI Features**, retry Download, check network |
| OpenMP / XGBoost on macOS | Install C++ OpenMP once: `brew install libomp` (required for AI Features / Harmonize contrast) |
| License errors | Check `aca_` length/format; validate online |
| Harmonize already running | Finish or cancel the other series |
| Tool greyed out | Install the matching CT/MR pack |

## Import and quarantine

| Symptom | What to try |
| --- | --- |
| Files ignored | Already imported (same SOP Instance) |
| Quarantine folders filling | Read folder name (Invalid_DICOM, Missing_Attributes, Lookup_Miss, …) |
| Lookup_Miss | Fix [lookup table](05-create-project/) or patient ID |

## Batch and memory

| Symptom | What to try |
| --- | --- |
| Low memory / stopped | Close other apps; fewer studies; see memory warning dialog |
| Everything skipped | Already processed—expected unless you clear status/cache |
| No series for studies | Selection has no readable DICOM series |

## Headless

Full guide: [Run without the window](10-headless/).

- `--ai-batch-run` needs **both** `-c` and `--ai-batch`
- Feature gates fail if models were never downloaded on that machine
- Empty `studies` / no PHI index → import in the GUI first

## Display

| Symptom | What to try |
| --- | --- |
| Welcome window tiny / clipped (macOS) | Use current V19; Tk 9 / uv reinstall tips in [Install](02-install/) |
| Projections fail on color US | Update to current V19 |
