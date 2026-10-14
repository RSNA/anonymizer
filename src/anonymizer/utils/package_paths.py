"""Packaged asset roots (CWD-independent).

All runtime AI weights and bundled data live under ``src/anonymizer/assets/``,
never a repo-root ``assets/`` tree resolved from the process working directory.
"""

from __future__ import annotations

from pathlib import Path

# ``utils/package_paths.py`` → package root ``anonymizer/``
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PACKAGE_ROOT / "assets"
AI_ASSETS_DIR = ASSETS_DIR / "ai"


def ai_feature_dir(*parts: str) -> Path:
    """Absolute path under ``assets/ai/<feature>/…``."""
    return AI_ASSETS_DIR.joinpath(*parts)
