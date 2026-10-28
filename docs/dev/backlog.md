# Product backlog (issue candidates)

Maintainer staging for GitHub Issues. Sourced from former root `TODO.md` and `# TODO` markers under `src/anonymizer/`. Inline comments stay until the matching issue is filed and closed.

Do not treat this file as CI scope or a substitute for Issues once items are filed.

## Ready to file

### Project private-creator allowlist for Retain Safe Private

Optional restriction on top of the full TCIA private-tag knowledge base: the user picks private creators relevant to their project; elements whose creator is not allowlisted fall through as unknown and are removed.

- Default: full KB (no restriction). Lookup is already keyed by creator — allowlist is a membership check before lookup.
- Store as a project field (creator strings, casefolded).
- Surface unknown-removed counts per creator in the ingest summary so sites can spot creators worth allowlisting.

### Overlapping burnt-in text detection (pixel path)

EasyOCR (CRAFT) merges overlapping two-line annotations into one garbled box or misses both lines when letter strokes intersect.

Example (date over name — `1st/Oct/1982` over `Stewart`):

![Overlapping burnt-in text: date over name](assets/overlapping-burnt-in-text.png)

Approach:

1. Baseline/component line separation before OCR: binarize → connected ink components → cluster into text lines by baseline/vertical centroid → render each line on its own canvas → existing OCR → NER frame-context path per line.
2. Benchmark a segmentation-based detector (PaddleOCR / DBNet polygons) on this crop plus `davidson_cxr` and `us_rgb_single_frame`.
3. Cheap EasyOCR threshold sweep first for reference (`mag_ratio`, `text_threshold` / `link_threshold`, `ycenter_ths` / `height_ths`) — helps only where strokes do not touch.

Constraints: pixel frame-context path only; report NER unchanged; no NER post-filters or span merging — separation is at the image level before the model.

Success: name and date return as separate boxes/entities on the example above; no regression on existing OCR fixture suites.

### NER model(s) for each other project language

Embedded PHI NER today only supports `en_US` (`SUPPORTED_DETECT_LOCALES`). Project UI languages also include German, Spanish, and French (`de` / `es` / `fr`).

- Ship or wire locale-appropriate NER model pack(s) for each non-English project language.
- Extend download/cache/detect so `detect_locale_supported` matches the project's language (or a documented fallback policy).
- Cover OCR→NER filter/classify and report-text paths; keep English behavior unchanged.
- Add at least one non-English fixture or smoke per locale once a model is chosen.

Pointers: `src/anonymizer/controller/ai/embedded_phi/ner/engine.py`; `ner/cache.py`; `utils/translate.py` (`language_to_code`).

### Safer project close and shutdown UX

- Do not allow project close while Import Files / Import Directory is busy.
- Shut down the controller asynchronously and show progress on the dashboard (especially anonymizer worker threads).
- Ensure the file menu is re-enabled via try/finally rather than scattered calls.

Pointers: `src/anonymizer/anonymizer.py` (file-menu enable; project close / shutdown).

### Windows DPI awareness and settings window icon

- Implement DPI awareness for views on Windows.
- `CTkToplevel` does not set the window icon correctly on Windows.

Pointers: `src/anonymizer/anonymizer.py`; `src/anonymizer/view/settings/settings_dialog.py`.

### Multi-database project storage

Expose database dialect in settings, infer file path vs URL, expand the project model beyond SQLite, and verify MySQL / PostgreSQL connection strings.

Pointers: `src/anonymizer/view/settings/settings_dialog.py`; `src/anonymizer/model/project.py`.

### Local SCP / SCU settings hygiene

- Checkbox to enable/disable network timeouts (`None` = no timeout).
- Prevent configuring the local server as a remote peer (same address/port).
- Reconsider whether `model.scu` should remain on the project model.

Pointers: `src/anonymizer/view/settings/settings_dialog.py`.

### AWS Cognito private user sub-directory option

Optional checkbox for a private user sub-directory via Cognito `get_user` `UserAttributes` (`sub`).

Pointers: `src/anonymizer/view/settings/aws_cognito_dialog.py`.

### Query / retrieve UX errors and echo cleanup

- Reflect query errors in the UI when the query was not aborted.
- Reconsider preflight C-ECHO before query and before C-STORE export; rely on connection errors from the real operation instead.

Pointers: `src/anonymizer/view/project/query_retrieve_import.py`; `src/anonymizer/view/project/export.py`.

### Import-studies retry and poll optimization

- Offer Retry to re-submit moves for unfinished studies.
- Poll only studies currently being moved.

Pointers: `src/anonymizer/view/project/import_studies_dialog.py`.

### Accession and stored-count query optimizations

- Use wildcard accession queries to cut down block/sequence FIND traffic.
- Compare stored-instance counting against in-memory PHI lookup.

Pointers: `src/anonymizer/view/project/query_retrieve_import.py`.

### FIND / MOVE robustness and helpers

Shared find helper for the routines below; clarify series-level vs instance-level behavior when series number is missing; optional multi-threaded find (similar to move).

Pointers: `src/anonymizer/controller/dicom/find_scu.py`.

### SCP large-dataset handling and quarantine

Investigate pynetdicom temporary storage for large datasets; decide when failed receives should go to quarantine.

Pointers: `src/anonymizer/controller/dicom/scp.py`.

### Store SCU memory and concurrency

Memory management for large datasets and many concurrent sends.

Pointers: `src/anonymizer/controller/dicom/store_scu.py`.

### Export / upload: multipart, transcoding, rollback

- Multi-part upload for large AWS objects.
- Optional password re-entry when credentials expire.
- Transcoding and DICOM compliance verification as project options.
- Clearer rollback on failed export steps.

Pointers: `src/anonymizer/controller/project.py`; `src/anonymizer/controller/anonymizer.py`.

### Export tree refresh performance

Updating export-tree values is I/O heavy; optimize refresh.

Pointers: `src/anonymizer/view/project/export.py`.

### Pixel PHI pipeline structure and source immutability

Split remove-pixel-PHI into pluggable sub-steps; optionally keep the source file immutable (backup parameter).

Pointers: `src/anonymizer/controller/ai/embedded_phi/pixel/remove_pixel_phi.py`.

### Series view: projection cleanup and whitelist errors

- Remove all-in-project projections when modality and image size are constant.
- Show a user-visible message when the OCR whitelist fails to load.

Pointers: `src/anonymizer/view/series/series.py`.

### Multi-frame pixel validation thoroughness

Decide whether every frame in the pixel array must be checked after decompress (vs trusting pydicom).

Pointers: `src/anonymizer/controller/series/series_io.py`.

## Smaller / needs triage

Single chore issue or individual micro-issues after triage:

| Topic | Pointer |
|-------|---------|
| Deep-copy nested classes/dicts by attribute on project clone | `src/anonymizer/anonymizer.py` |
| Rename `@round` operand to age-specific name | `src/anonymizer/controller/anonymizer.py` |
| Add Body Part Examined on hierarchy records | `src/anonymizer/controller/dicom/hierarchies.py` |
| Wire SQLAlchemy engine logging via existing dbengine helper | `src/anonymizer/model/anonymizer.py` |
| `ux_fields` geometry/accuracy question | `src/anonymizer/view/common/ux_fields.py` |
