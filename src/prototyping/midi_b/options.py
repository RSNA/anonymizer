"""Product de-identification options used by the MIDI-B eval harness."""

from anonymizer.utils.dicom import DeidMethodCode
from anonymizer.view.settings.deidentification_options_dialog import RETAIN_OPTIONS

# Retain preset + Retain TCIA Research. Retain Device Identity stays off:
# MIDI-B / current TCIA expect Device Serial and Station Name removed; TCIA
# Research @safe()s manufacturer / model / software instead.
MIDI_B_OPTIONS: frozenset[DeidMethodCode] = RETAIN_OPTIONS | {
    DeidMethodCode.TCIA_RESEARCH,
}
