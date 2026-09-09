"""Optional OS filesystem drag-and-drop (tkdnd via tkinterdnd2).

Experimental: soft-fails if tkdnd binaries are missing or incompatible with the
host Tcl/Tk. File → Import remains the primary path.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

_dnd_required_roots: set[int] = set()


def enable_filesystem_drops(
    widget: Any,
    on_paths: Callable[[list[str]], None],
) -> bool:
    """Register ``DND_FILES`` on ``widget``. Returns False if DnD is unavailable."""
    try:
        from tkinterdnd2 import DND_FILES, TkinterDnD
    except Exception as exc:
        logger.warning("File drop unavailable (tkinterdnd2 import failed): %s", exc)
        return False

    try:
        root = widget.winfo_toplevel()
        root_id = id(root)
        if root_id not in _dnd_required_roots:
            TkinterDnD.require(root)
            _dnd_required_roots.add(root_id)

        widget.drop_target_register(DND_FILES)

        def _on_drop(event: Any) -> None:
            try:
                raw = widget.tk.splitlist(event.data)
            except Exception:
                logger.exception("Failed to parse dropped paths")
                return
            paths = [str(p).strip() for p in raw if str(p).strip()]
            if not paths:
                return
            # Defer off the DnD callback: opening a modal + wait_window inside
            # <<Drop>> nests the event loop and leaves Import Files stuck on Close.
            root = widget.winfo_toplevel()
            root.after(1, lambda paths=list(paths): on_paths(paths))

        widget.dnd_bind("<<Drop>>", _on_drop)
        logger.info("File drop enabled on %s", type(widget).__name__)
        return True
    except Exception as exc:
        logger.warning("File drop unavailable on %s: %s", type(widget).__name__, exc)
        return False
