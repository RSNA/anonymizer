# Process

**Process** tools change anonymized **pixels** or **series / study names** after import. Work on **one series** in Series View (opened from [View](../07-view/)), or on **many studies** from Dataset ([AI Batch Process](05-run-on-many-studies/)).

Models and licenses are set up once from Welcome — see [AI Features setup](../03-ai-features-setup/) before the tool chapters below.

## Tools

| Chapter | Tool | Demo series | What you practice |
| --- | --- | --- | --- |
| 8.1 | [Remove Pixel PHI](02-remove-burned-in-text/) (burned-in text) | **`davidson_cxr`**, **`us_rgb_single_frame`** | Detect → black out; Detect → blend into background |
| 8.2 | [Harmonize names](03-harmonize-names/) | **`Brain_Ax_EarlyArt`** | Series View → results → brain prompt → segmented middle slice |
| 8.3 | [Blur faces](04-blur-faces/) | **`Brain_Ax_EarlyArt`** | Face blur, **Gaussian** mode |
| 8.4 | [Run on many studies](05-run-on-many-studies/) | Selected studies | Batch the same tools across a cohort |

Demo series live under `tests/controller/assets/test_dcm_files/`. Import them ([Search](../06-search/)), then open Series View from Dataset ([View](../07-view/) — right-click the series).

## Order to learn

1. Finish [AI Features setup](../03-ai-features-setup/) so models are ready.
2. Walk **Remove Pixel PHI** on `davidson_cxr` (black out), then try blend on `us_rgb_single_frame`.
3. Walk **Harmonize**, then **Face blur**, on the same `Brain_Ax_EarlyArt` series.
4. Use **Run on many studies** when you need the same tools on a cohort.

## Next steps

1. Start with [8.1 Remove Pixel PHI](02-remove-burned-in-text/)
2. After processing looks good, [Send](../09-send/) anonymized patients, or [run without the window](../10-headless/) on a lab server
