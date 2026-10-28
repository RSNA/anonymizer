# Process

**Process** finishes de-identification work that import does not: scrub burnt-in text on images, find leftover PHI in free-text tags and reports, standardize series and study names with Harmonize, and blur faces on eligible head exams. Run a tool on one series in [Series View](../07-view/index.md#series-view-what-you-can-do) by right-clicking the series in Dataset, or on many studies with [AI Batch Process](05-run-on-many-studies/index.md) from Dataset.

To spot-check DICOM tags without changing them, use Series View [Metadata](../07-view/index.md#metadata-dicom-tags). After Harmonize on CT or MR, latch anatomy chips or paint user ROIs in [Annotation](../07-view/index.md#annotation). Annotation segments are 3D on CT and MR, and 2D on planar XR, US, and MG.

Models and licenses are set up once from Welcome — see [AI Features setup](../03-ai-features-setup/index.md) before the tool chapters below.

## Site workflow {#recommended-site-workflow}

QA a few series in Series View, then scale with AI Batch from Dataset:

1. **Import** via [Search](../06-search/index.md); open samples in [Series View](../07-view/index.md#series-view-what-you-can-do).
2. **Harmonize** a CT/MR and planar sample; fix names with [Set description](../07-view/index.md#edit-study-and-series-descriptions) and [Description Mappings](../07-view/index.md#description-mappings). Latch or paint in [Annotation](../07-view/index.md#annotation). CT/MR organ volumes: [Analytics](../07-view/index.md#analytics).
3. **Face blur** on an eligible head series; keep the mode you will batch (demo: Gaussian).
4. **Embedded PHI** — [8.1](02-remove-burned-in-text/index.md): [Pixel](02-remove-burned-in-text/index.md#pixel), [Metadata](02-remove-burned-in-text/index.md#metadata), and [Reports](02-remove-burned-in-text/index.md#reports) on samples.
5. **Batch** the same options on the cohort with [AI Batch Process](05-run-on-many-studies/index.md); leave Prefer description mappings on.

Chapters 8.1–8.3 teach each tool; 8.4 is the cohort step.

## Tools

| Chapter | Tool | Demo series | What you practice |
| --- | --- | --- | --- |
| 8.1 | [Embedded PHI](02-remove-burned-in-text/index.md) — [Pixel](02-remove-burned-in-text/index.md#pixel) / [Metadata](02-remove-burned-in-text/index.md#metadata) / [Reports](02-remove-burned-in-text/index.md#reports) | `davidson_cxr`, `us_rgb_single_frame`, `demo_report_pdf` | Pixel Detect→Remove; Metadata Detect PHI; Report Text Review |
| 8.2 | [Harmonize names](03-harmonize-names/index.md) | `CT_Head_With_Contrast`, `davidson_cxr`, `us_rgb_single_frame` | CT results + brain prompt; [Annotation](../07-view/index.md#annotation) 2D/3D; CT/MR [Analytics](../07-view/index.md#analytics) organ volumes; planar XR/US Playbook |
| 8.3 | [Blur faces](04-blur-faces/index.md) | `CT_Head_With_Contrast` | Face blur, Gaussian mode |
| 8.4 | [Run on many studies](05-run-on-many-studies/index.md) | Selected studies | Batch the same tools across a cohort |

Demo series and screenshots come from the source repository folder `tests/controller/assets/test_dcm_files/` ([browse on GitHub](https://github.com/RSNA/anonymizer/tree/dev/tests/controller/assets/test_dcm_files); see [Search — Demo studies from the repository](../06-search/index.md#demo-studies-from-the-repository)). Import them, then open Series View from Dataset ([View](../07-view/index.md) — right-click the series).

## Order to learn

1. Finish [AI Features setup](../03-ai-features-setup/index.md) so models are ready.
2. Walk Embedded PHI [Pixel](02-remove-burned-in-text/index.md#pixel) on `davidson_cxr` / `us_rgb_single_frame`, then [Metadata](02-remove-burned-in-text/index.md#metadata) and [Reports](02-remove-burned-in-text/index.md#reports) on a sample report if available.
3. Walk Harmonize on `CT_Head_With_Contrast`, then the planar demos on `davidson_cxr` and `us_rgb_single_frame`; review or paint segments in [Annotation](../07-view/index.md#annotation); on CT/MR check Harmonize organ-volume charts in [Analytics](../07-view/index.md#analytics); Face blur on the same CT head series.
4. Use Run on many studies when you need the same tools on a cohort — see [Site workflow](#recommended-site-workflow) for the intended Series View QA → Dataset batch pattern.

## Next steps

1. Start with [8.1 Embedded PHI](02-remove-burned-in-text/index.md)
2. After processing looks good, [Send](../09-send/index.md) anonymized patients, or [run headless](../10-headless/index.md) on a lab server
