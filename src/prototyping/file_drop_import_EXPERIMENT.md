"""Experimental File menu import via OS drag-and-drop (Dashboard / Dataset).

Branch: ``experiment/file-drop-import``

How to try
----------
1. ``uv sync`` (pulls ``tkinterdnd2``)
2. ``uv run rsna-anonymizer``
3. Open a project; drag DICOM files or one folder from Finder/Explorer onto the
   **Dashboard** or **Dataset** window
4. Confirm the same ``ImportFilesDialog`` path as File → Import

Soft-fail: if tkdnd cannot load, File → Import still works; check logs for
``File drop unavailable``.
"""
