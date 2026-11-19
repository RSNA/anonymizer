# 19.1.0 stable cut checklist

Maintainer gate for merging `dev` into `master` as **stable 19.1.0** (not another `19.1.0.devN`).

Audience: maintainers. Not part of the clinician MkDocs site. Related backlog: [backlog.md](backlog.md).

Current pre-release line (as of this checklist): `19.1.0.dev8` on `dev`. Stable on `master` remains **19.0.10** until this cut.

---

## 1. Scope freeze

Confirm each 19.1 theme from CHANGELOG (`dev1`–`dev8`) is either **in** the release or **explicitly deferred** with a note:

- [x] De-identification Options (Basic / Retain) and DICOM PS 3.15 § E.1.3 / HIPAA wording
- [x] Embedded PHI: pixel OCR path, metadata Clean Descriptors, report text / Clean Structured Content
- [x] Harmonize (CT/MR + planar) and Dataset Set description; description OAS **off** by default (priors stay in PHI DB / lookup CSV)
- [x] CTP / TCIA script import (operands, lookup stamps, Import CTP Script UX)
- [x] DICOMweb (QIDO / WADO / STOW) when enabled on a remote
- [x] Storage free-space gates (refuse C-STORE / import / export when critically low)
- [x] MCP: documented as **experimental / opt-in** for 19.1.0 (start with `--mcp`; FastMCP is a core dep so default install launches; see `docs/*/10-headless/`) — not the recommended default workflow vs GUI / `-c`

Blocking bugs:

- [x] No open P0/P1 on PHI left in export, wrong description rewrite, or import/export data loss
- [x] No open P0/P1 on project open/upgrade from 19.0.10 (`ProjectModel` version 12 path)

**Do not block 19.1** on these backlog items (track post-cut; see [backlog.md](backlog.md)):

- [x] Acknowledged deferred: MIDI-B pixel PHI gold-string misses (12 cases)
- [x] Acknowledged deferred: NER models for non-English project languages
- [x] Acknowledged deferred: private-creator allowlist for Retain Safe Private
- [x] Acknowledged deferred: multi-database project storage; Windows DPI / settings icon; safer project-close UX; FIND/MOVE UX polish and similar backlog entries

---

## 2. Soak / field validation

- [ ] Fresh install via `uv pip install --pre rsna-anonymizer` reports `19.1.0.dev8` or a later `19.1.0.devN` if more land before the cut
- [ ] Upgrade soak: open an existing **19.0.10** project on the pre-release build; confirm model load / version upgrade path and basic Dataset browse
- [ ] Fresh project soak: create a new project on the pre-release build

Smoke (on real or fixture data):

- [ ] Import Files / Import Directory
- [ ] Find / Retrieve **or** DICOMweb query + retrieve (whichever you claim for sites)
- [ ] Series View: OCR detect + remove (or document pixel PHI as optional AI feature)
- [ ] Harmonize at least one CT/MR **or** planar study; Set description from Dataset
- [ ] Export to a remote or local destination
- [ ] Low-disk refuse path exercised once (or unit-covered path accepted as sufficient)

---

## 3. Automated quality

- [ ] Default suite green on `dev`: `uv run pytest` (markers excluded by `addopts` as usual)
- [ ] If DICOMweb / DIMSE are marketed for 19.1: `dicom_integration` run (Orthanc) and known failures triaged
- [ ] If MIDI-B / OCR scores are still claimed in docs: relevant `midi_b_integration` / `ocr_integration` runs reviewed (misses already listed in backlog do not block if documented)
- [ ] MCP: keep live e2e as opt-in (`mcp_e2e`); docs still call the server experimental / `--mcp` opt-in (FastMCP is a core dep)
- [ ] Coverage: default TOTAL ~84% is **not** a hard gate. Follow-ups after cut (not blockers): high-miss areas such as `mcp/ops.py`, remaining `model_cache` / `segment` edges, `project` AWS paths, DIMSE `find_scu` branches

---

## 4. Docs and packaging for stable

- [ ] CHANGELOG: add `## [19.1.0]` summarizing the ship; fold Unreleased / last `.devN` bullets; drop “PyPI development pre-release” wording for the stable section
- [ ] `pyproject.toml` version = `19.1.0`
- [ ] `readme.md` / `readme.de.md` / `readme.es.md` / `readme.fr.md`: stable **19.1.0** without `--pre`; clarify next pre-release lives on `dev` after the cut
- [ ] `docs/{en,de,es,fr}/02-install/index.md`: same version wording
- [ ] `uv.lock` package version matches `19.1.0`
- [ ] Clinician help matches ship: OAS-off for Harmonize / Set description; De-identification Options chapters; no screenshots that show obsolete OAS-on description behavior
- [ ] Spot-check View / Process chapters touched in 19.1 for screenshot drift

---

## 5. Cut procedure

- [ ] On `dev` (or a short-lived release branch from `dev`): bump to **19.1.0**, commit with release message style used for prior stables
- [ ] Tag `19.1.0` and push tag → [`.github/workflows/release.yaml`](../../.github/workflows/release.yaml) publishes to PyPI
- [ ] Confirm GitHub Actions release run succeeded and `pip` / `uv pip install rsna-anonymizer` (no `--pre`) resolves to **19.1.0**
- [ ] Merge `dev` into `master` (or fast-forward) so `master` matches the tagged stable tree
- [ ] Re-open `dev` for the next line: bump to `19.2.0.dev1` (or agreed next) so `--pre` does not collide with stable 19.1.0
- [ ] Update install docs on `dev` for the new pre-release; leave `master` docs on 19.1.0

---

## Done when

All sections above are checked (or explicitly waived in a short note under Scope freeze). Then `master` is the supported install line and `dev` is open for post-19.1 work.
