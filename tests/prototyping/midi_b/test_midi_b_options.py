"""MIDI-B harness uses product options with no post-compile keep exceptions."""

from anonymizer.utils.dicom import DeidMethodCode
from anonymizer.view.settings.deidentification_options_dialog import RETAIN_OPTIONS
from prototyping.midi_b.options import MIDI_B_OPTIONS
from prototyping.pseudo_phi_deid.pipeline import script_session


def test_midi_b_options_are_retain_tcia_without_device() -> None:
    """Validate stack is Retain preset + TCIA Research; Device Identity off."""
    assert MIDI_B_OPTIONS == RETAIN_OPTIONS | {DeidMethodCode.TCIA_RESEARCH}
    assert DeidMethodCode.DEVICE_IDENTITY not in MIDI_B_OPTIONS


def test_script_session_has_no_midi_keep_tag_exceptions() -> None:
    """Harness must not carry deleted post-compile keep-tag constants."""
    assert not hasattr(script_session, "_MIDI_RESEARCH_KEEP_TAGS")
