# MkDocs help screenshots (`docs_help`)

Maintainer tooling that drives the Anonymizer UI and writes PNGs for the
clinician manual under `docs/<lang>/<chapter>/shots/<os>/`.

**Not** part of the shipped `rsna-anonymizer` wheel.

## Layout

```
src/docs_help/
  cli.py / capture.py / handlers.py   # entry + runner + shot recipes
  manifest.py                         # docs/screenshots-manifest.yaml
  project_setup.py / orthanc.py       # fixtures + Orthanc helpers
  harmonize.py / series_view_export.py
  platform/
    common.py                         # settle, normalize (shared)
    macos.py                          # screencapture -l + CGWindow
    windows.py                        # visible DWM frame (screen BitBlt) / PrintWindow fallback
```

## Developer workflow (macOS + Windows)

Capture must run on the real OS (window chrome cannot be faked).

1. Check out the latest branch on a **macOS** machine
2. Orthanc on `127.0.0.1:4242` (AE `ORTHANC`) for Search/Query shots; grant Screen Recording
3. Run full capture (all languages in order **en_US → de → es → fr**; writes `shots/macos/`). Existing PNGs stay on disk (`exists` in the end-of-run table) so you can re-run to resume:

```bash
uv run python -m docs_help -v
```

One language only:

```bash
uv run python -m docs_help --language de -v
uv run python -m docs_help --language en_US --force --only Welcome
```

4. Repeat on a **Windows** machine with the same commit (writes `shots/windows/`)
5. Commit both `shots/macos/` and `shots/windows/` trees and push

`--platform auto` (default) uses the host OS. Cross-OS capture is refused.

Markdown embeds the macOS path (`shots/macos/….png`). The published site’s
`docs/javascripts/os_shots.js` swaps to `shots/windows/` for Windows visitors,
falling back to macOS if a Windows PNG is missing.

See also [`docs/en/screenshots-style-guide.md`](../../docs/en/screenshots-style-guide.md).
