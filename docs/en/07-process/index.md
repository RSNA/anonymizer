# Process

**Process** tools change anonymized pixels or series names after import. Work on **one series** in Series View, or on **many studies** from Dataset (AI Batch Process).

## Chapters

| # | Chapter | Demo series | What you practice |
| --- | --- | --- | --- |
| 7.1 | [AI Features setup](01-ai-features-setup/) | — | Download models and licenses once |
| 7.2 | [Remove burned-in text](02-remove-burned-in-text/) | **`davidson_cxr`** | Default whitelist → Frame → Detect → Remove |
| 7.3 | [Harmonize names](03-harmonize-names/) | **`Brain_Ax_EarlyArt`** | Harmonize Description → Segment Brain Features |
| 7.4 | [Blur faces](04-blur-faces/) | **`Brain_Ax_EarlyArt`** | Face blur, **Gaussian** mode |
| 7.5 | [Run on many studies](05-run-on-many-studies/) | Selected studies | Batch the same tools across a cohort |

Demo series live under `tests/controller/assets/test_dcm_files/`. Import them into a project before opening Series View.

## Order to learn

1. Finish **7.1** so models are ready.
2. Walk **7.2** on `davidson_cxr`.
3. Walk **7.3** then **7.4** on the same `Brain_Ax_EarlyArt` series.
4. Use **7.5** when you need the same tools on many studies.

## Next steps

1. Start with [7.1 AI Features setup](01-ai-features-setup/)
2. After processing looks good, [Send](../08-send/) anonymized patients, or [run without the window](../09-headless/) on a lab server
