"""Stable paths to shared test assets (repo-root relative)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ANONYMIZER_SCRIPT = REPO_ROOT / "src/anonymizer/assets/scripts/default-anonymizer.script"
