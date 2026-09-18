"""PhotoImage disposal must be safe when GC runs off the main thread.

Reproduces the macOS bus error seen when ``PIL.ImageTk.PhotoImage.__del__``
runs on a pynetdicom worker after analytics charts / series images are dropped.
"""

from __future__ import annotations

import contextlib
import gc
import os
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image, ImageTk

from anonymizer.utils.memory import collect_garbage_safe
from anonymizer.view.common.ctk_safe import (
    dispose_photo_image,
    release_mpl_frame_images,
)


@pytest.fixture
def tk_root():
    root = tk.Tk()
    root.withdraw()
    try:
        yield root
    finally:
        with contextlib.suppress(tk.TclError):
            root.destroy()


def _make_photo(root: tk.Tk, *, size: tuple[int, int] = (32, 32)) -> ImageTk.PhotoImage:
    pil = Image.new("RGBA", size, (10, 20, 30, 255))
    return ImageTk.PhotoImage(pil, master=root)


def test_dispose_photo_image_neutralizes_imagetk_del_off_main_thread(tk_root) -> None:
    """After dispose, ImageTk.__del__ must not call into Tcl from a worker."""
    photo = _make_photo(tk_root)
    assert getattr(photo, "_PhotoImage__photo", None) is not None

    dispose_photo_image(tk_root, photo)

    assert getattr(photo, "_PhotoImage__photo", "missing") is None

    errors: list[BaseException] = []

    def _finalize_on_worker() -> None:
        try:
            ImageTk.PhotoImage.__del__(photo)
        except BaseException as exc:  # noqa: BLE001 — capture any crash-path error
            errors.append(exc)

    worker = threading.Thread(target=_finalize_on_worker, name="FakeDicomThread")
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert errors == []


def test_dispose_photo_image_then_worker_gc_collect_does_not_crash(tk_root) -> None:
    """Orphaned disposed photos must survive worker-thread ``gc.collect``."""
    photos = [_make_photo(tk_root) for _ in range(12)]
    for photo in photos:
        dispose_photo_image(tk_root, photo)
    photos.clear()

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def _worker_gc() -> None:
        try:
            barrier.wait(timeout=5)
            for _ in range(3):
                gc.collect()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    worker = threading.Thread(target=_worker_gc, name="FakeDicomThread")
    worker.start()
    barrier.wait(timeout=5)
    collect_garbage_safe(generations=2)
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert errors == []


def test_release_mpl_frame_images_disposes_direct_photoimages(tk_root) -> None:
    """Chart cells store (label, PhotoImage, PIL) like ImageViewer.image_cache."""
    frame = tk.Frame(tk_root)
    frame.pack()
    pil = Image.new("RGBA", (24, 24), (1, 2, 3, 255))
    photo = ImageTk.PhotoImage(pil, master=tk_root)
    label = tk.Label(frame, image=photo)
    label.image = photo  # type: ignore[attr-defined]
    label.pack()
    frame._mpl_images = [(label, photo, pil)]  # type: ignore[attr-defined]

    release_mpl_frame_images(frame)

    assert frame._mpl_images == []  # type: ignore[attr-defined]
    assert getattr(photo, "_PhotoImage__photo", "missing") is None

    errors: list[BaseException] = []

    def _worker_gc() -> None:
        try:
            gc.collect()
            ImageTk.PhotoImage.__del__(photo)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(_worker_gc).result(timeout=5)
    assert errors == []


def test_repeated_embed_release_cycle_memory_stable(tk_root) -> None:
    """Create/dispose many chart-sized PhotoImages without unbounded RSS growth."""
    psutil = pytest.importorskip("psutil")
    process = psutil.Process(os.getpid())

    collect_garbage_safe(generations=2)
    rss_before = process.memory_info().rss

    frame = tk.Frame(tk_root)
    frame.pack()
    for _cycle in range(8):
        refs: list = []
        for _ in range(10):
            pil = Image.new("RGBA", (180, 120), (40, 50, 60, 255))
            photo = ImageTk.PhotoImage(pil, master=tk_root)
            label = tk.Label(frame, image=photo)
            label.image = photo  # type: ignore[attr-defined]
            label.pack()
            refs.append((label, photo, pil))
        frame._mpl_images = refs  # type: ignore[attr-defined]
        release_mpl_frame_images(frame)
        for child in list(frame.winfo_children()):
            child.destroy()
        collect_garbage_safe(generations=2)

    rss_after = process.memory_info().rss
    growth_mb = (rss_after - rss_before) / (1024 * 1024)
    # Allow allocator noise; fail on clear leak of many RGBA chart bitmaps.
    assert growth_mb < 40.0, f"PhotoImage cycle leaked ~{growth_mb:.1f} MB"


def test_collect_garbage_safe_skips_off_main_while_photos_live(tk_root) -> None:
    """Worker must not run gc.collect while undisposed photos exist (memory helper)."""
    photo = _make_photo(tk_root)
    held = [photo]

    def _worker() -> None:
        collect_garbage_safe(generations=2)

    worker = threading.Thread(target=_worker)
    worker.start()
    worker.join(timeout=5)
    assert held[0] is photo
    dispose_photo_image(tk_root, photo)
    held.clear()
