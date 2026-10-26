"""Unit tests for MIDI-B failure taxonomy (no dataset required)."""

from prototyping.midi_b.taxonomy import TAXONOMY_BUCKETS, classify_action


def test_classify_residual_and_over_scrub() -> None:
    assert classify_action("<text_removed>") == "residual_phi"
    assert classify_action("<pixels_hidden>") == "residual_phi"
    assert classify_action("<text_retained>") == "over_scrub"
    assert classify_action("<tag_retained>") == "over_scrub"
    assert classify_action("<text_notnull>") == "over_scrub"


def test_classify_uid_and_private() -> None:
    assert classify_action("<uid_changed>") == "uid_action"
    assert classify_action("<uid_consistent>") == "uid_action"
    assert classify_action("<date_shifted>") == "uid_action"
    assert (
        classify_action("<text_removed>", tag_ds="<(0019,1000)>") == "private_tag"
    )
    assert (
        classify_action("<text_retained>", tcia_ptkb="TCIA-PTKB-1") == "private_tag"
    )


def test_classify_other_and_bucket_set() -> None:
    assert classify_action("<unknown_action>") == "other"
    assert set(TAXONOMY_BUCKETS) == {
        "residual_phi",
        "over_scrub",
        "uid_action",
        "private_tag",
        "other",
    }
