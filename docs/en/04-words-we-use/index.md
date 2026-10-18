# Words we use

Short glossary for clinicians. When IT uses different terms, these are usually the same ideas.

| Word | Meaning |
| --- | --- |
| **Study** | One exam visit (for example a CT chest). May contain several series. |
| **Series** | One set of related images (for example axial thin slices, or a scout). |
| **Instance / image** | A single frame or slice file. |
| **PHI** | Protected health information — identifiers that could reveal who the patient is. |
| **De-identify / anonymize** | Remove or replace identifiers so the study is safer to share for research. |
| **Anonymizer script** | XML rules that list DICOM tags to keep, remove, or transform. Edit from **Project Settings → Edit Anonymizer Script**. |
| **Burned-in text** | Words drawn onto the picture itself (not only in the file labels). Common on ultrasound. |
| **Embedded PHI** | Identifiers inside pixels (burned-in text) or free text (reports, comments), found after import with OCR and English NER. |
| **Blank / Synthetic** | Two ways to remove text PHI: delete it, or replace it with a realistic fake of the same type (“hide in plain sight”). |
| **Anonymization policy** | **Strict** (default, image-focused) or **Clinical** (keeps reports, clinical free text; SR/PDF on). Switching on an existing project replaces the project script after you confirm. Set in Project Settings. |
| **Metadata** | The DICOM tag tree for the current image in Series View. **Detect PHI** highlights leftover identifiers in tag values (separate from burned-in pixel text). |
| **Analytics** | Dashboard charts of organ volumes after Harmonize on CT/MR (cohort overview, not a send step). |
| **Quarantine** | A holding folder for files that could not be imported (wrong type, missing IDs, lookup miss, etc.). |
| **Dataset** | The in-app list of patients, studies, and series in your project (formerly called PHI Index). |
| **Project** | A named workspace with its own settings and storage folder. |
| **Whitelist (OCR)** | Allowed short labels (for example L/R) that should **not** be removed when cleaning burned-in text. |
| **Exclude Area** | A region on the image that Detect / Remove Embedded PHI skip (for machine overlays that are not PHI). |

!!! note "When you talk to IT"
    Terms like **AE Title**, **SOP Class**, **transfer syntax**, and **C-MOVE** describe how systems talk to each other. You usually only need them when connecting to a hospital archive—see [Create a project → When you talk to IT](../05-create-project/#when-you-talk-to-it).

## Next steps

Continue with [Create a project](../05-create-project/).
