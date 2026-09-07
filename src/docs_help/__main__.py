"""``python -m docs_help`` entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow ``uv run python -m docs_help`` when the package is not installed in the wheel.
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from docs_help.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
