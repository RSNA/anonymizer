# RSNA DICOM Anonymizer MCP

How to call the working tools.

## Session

- One project open at a time: `create_project`, `project_open`, `list_projects`, `project_info`.

## Ingest

- `import_directory` / `import_file` — absolute host paths.

## Inventory

- `list_inventory` → read field `table` (TSV). Columns:
  `patient_index study_index series_index anon_patient_id modality study_description study_harmonized series_description series_harmonized pixel_phi_scanned`
- Address series with indices from that table only:
  - `patient`: `"all"` | `"<patient_index>"` | `"<anon_patient_id>"`
  - `study`: `"all"` | `"<study_index>"`
  - `series`: `"all"` | `"<series_index>"` | modality | description substring
- Report descriptions only from `study_description` / `series_description` (never invent text).

## Process

- `remove_pixel_phi` — `{"series": "all"}` or `{"patient": "1", "series": "1"}`
- `harmonize_studies` — series then study descriptions: `{}` / `{"patient": "all"}` / `{"patient": "1", "study": "1"}`
- `export_series_preview` — PNG/JPEG as `preview_base64` + `mime_type` (no disk path).
  Example: `{"patient": "1", "series": "1"}`

## Call sequence

| Step | Tool | Arguments |
| --- | --- | --- |
| 1 | `create_project` | `{"project_name": "MCP_MVP"}` |
| 2 | `import_directory` | `{"directory": "/absolute/path/to/dicom/folder"}` |
| 3 | `list_inventory` | `{}` |
| 4 | `remove_pixel_phi` | `{"series": "all"}` |
| 5 | `harmonize_studies` | `{}` |
| 6 | `list_inventory` | `{}` |
| 7 | `export_series_preview` | `{"patient": "1", "series": "1"}` |
