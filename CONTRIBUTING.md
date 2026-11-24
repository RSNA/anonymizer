# Contributing

Thanks for helping with the RSNA DICOM Anonymizer. This page covers the basics for issues and pull requests.

## Branches

- Open pull requests against **`dev`**. `master` is the stable release line.
- Keep each pull request to one change. Small, tested PRs are the quickest to review.
- For a larger change (a new feature, a new dependency, a UI flow), open an issue first so the approach can be agreed before you write the code.

## Set up

You need [uv](https://docs.astral.sh/uv/) and Python 3.11 to 3.14 with **tkinter** (see [Install](readme.md#install)). Fork the repository on GitHub, clone your fork, and branch from upstream `dev` (a default fork copies only `master`):

```bash
git clone https://github.com/<your-user>/anonymizer.git
cd anonymizer
git remote add upstream https://github.com/RSNA/anonymizer.git
git fetch upstream
git checkout --no-track -b my-change upstream/dev
uv sync --group dev
uv run pre-commit install
```

## Before you open a pull request

Run the same checks as the main CI job:

```bash
uv run ruff check ./src/anonymizer/
uv run pytest -q
```

- Ruff settings live in `[tool.ruff]` in `pyproject.toml`. Imports stay at module top (`PLC0415`).
- Tests mirror the source tree (`tests/controller/` for `src/anonymizer/controller/`, and so on). Add or update tests with your change.
- Opt-in suites (Orthanc, OCR, MIDI-B, GUI) and their markers are described in [tests/README.md](tests/README.md). They are not needed for most PRs.
- CI runs on Python 3.11 to 3.14 and installs with `uv sync --group dev --locked`. If you change dependencies, commit the updated `uv.lock`.
- For a user-visible change, add a line to [CHANGELOG.md](CHANGELOG.md).
- Commit messages: one plain sentence ending in a period, like the existing history.

## Test data

- Use synthetic or openly licensed DICOM only: pydicom's bundled files (`pydicom.data.get_testdata_file`) or the fixtures in `tests/controller/assets/`.
- Never commit, attach or paste real patient data (PHI). That includes issues, screenshots, logs and files. Check them before you post.

## Issues

Use the bug report or feature request template. For bugs, include `rsna-anonymizer --version`, your OS and your Python version.

## Security

Do not open a public issue for a vulnerability. Follow [SECURITY.md](SECURITY.md), which uses GitHub private vulnerability reporting.

## Code of Conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
