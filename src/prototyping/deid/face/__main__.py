"""Deprecated shim — use ``python -m prototyping.ffr.face`` instead."""

from prototyping.ffr.face.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
