# Documentation (MkDocs)

Clinician user manual for the RSNA DICOM Anonymizer.

## Layout

| Path | Role |
| --- | --- |
| [`mkdocs.yml`](../mkdocs.yml) | MkDocs config at **repo root** (MkDocs default; do not nest under `docs/`) |
| `docs/en/` | English pages — **source of truth** (`docs_structure: folder` + i18n plugin) |
| `docs/de/`, `docs/es/`, `docs/fr/` | Locale mirrors (same chapter paths as `docs/en/`) |
| `docs/assets/` | Site chrome (logo, favicon) |
| `docs/javascripts/` | Site scripts (e.g. OS-specific screenshot swap) |
| `docs/stylesheets/` | Extra CSS |
| `docs/screenshots-manifest.yaml` | Catalog of help UX screenshots |
| `docs/<lang>/<chapter>/shots/{macos,windows}/` | Captured PNGs per UI language |
| `docs/en/10-headless/AiBatchConfig.example.json` | Sample headless AI batch config (not a separate `docs/examples/` tree) |

Screenshot capture tooling: [`src/docs_help/`](../src/docs_help/README.md).

## Locale status (vs English)

Update this table when a locale catches up or lags after an English docs change.

| Locale | Markdown | Screenshots | Notes |
| --- | --- | --- | --- |
| `en` | Current | macOS + Windows (partial) | Source of truth |
| `de` | Full chapter set translated (machine draft; needs native review) | Windows shots present for many chapters; macOS TBD | Phase C complete pending review |
| `es` | Full chapter set translated (machine draft; needs native review) | Not captured yet | Phase C complete pending review |
| `fr` | Full chapter set translated (machine draft; needs native review) | Not captured yet | Phase C complete pending review |

**Process:** freeze English → machine draft → native review → link check. Do not merge unreviewed machine translation to `master`.

## Build / serve

```bash
uv sync --group docs
uv run mkdocs serve
uv run mkdocs build
```

Published site: https://rsna.github.io/anonymizer/ (language switcher for `en` / `de` / `es` / `fr`).

## Logo

Header logo and favicon are copies under `docs/assets/`, sourced from `src/anonymizer/assets/icons/` (`rsna_icon.png` / `rsna_icon.ico`). Material’s header logo works best as PNG or SVG; the Windows `.ico` is used as the **favicon** only.

## Colors

MkDocs Material uses `primary: custom` / `accent: custom` with CSS in [`stylesheets/extra.css`](stylesheets/extra.css), aligned to [`src/anonymizer/assets/themes/rsna_theme.json`](../src/anonymizer/assets/themes/rsna_theme.json):

- Header / brand (light): `#014F8F` (app label / border tone)
- Accent / controls: `#3a7ebf` (app button fill)
- Dark scheme primary: `#1f538d` (app dark-mode button fill)
