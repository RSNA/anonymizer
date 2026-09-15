"""Manifest chapter order and language sequence for help screenshot capture."""

from __future__ import annotations

from docs_help.manifest import EXPECTED_CHAPTERS, chapter_sort_key, load_manifest


def test_manifest_help_chapter_shot_order() -> None:
    manifest = load_manifest()
    chapters = tuple(wf.chapter for wf in manifest.workflows)
    assert chapters == EXPECTED_CHAPTERS
    assert chapter_sort_key("8.2") < chapter_sort_key("9")
    labels = [f"{wf.chapter} {wf.title}" for wf in manifest.workflows]
    assert labels[6] == "8.2 Harmonize names"
    assert labels[-1] == "9 Send"
    assert labels.index("8.2 Harmonize names") < labels.index("9 Send")

    harmonize = next(wf for wf in manifest.workflows if wf.chapter == "8.2")
    assert [s.id for s in harmonize.shots] == [
        "Process_Harmonize_Description",
        "Process_Harmonize_BrainPrompt",
        "Process_Harmonize_SegmentedSeries",
        "Process_Harmonize_CXR",
        "Process_Harmonize_US",
    ]
    assert all(s.chapter_label == "8.2 Harmonize names" for s in harmonize.shots)


def test_language_codes_start_at_english_then_de_es_fr() -> None:
    manifest = load_manifest()
    assert manifest.language_codes() == ("en_US", "de", "es", "fr")
