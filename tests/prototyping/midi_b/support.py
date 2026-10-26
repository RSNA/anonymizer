"""Readiness helpers and paths for MIDI-B adversarial pytest suite."""

from __future__ import annotations

import json
import os
from pathlib import Path

from prototyping.midi_b.paths import (
    DEFAULT_ANSWER_KEY_VALIDATION,
    DEFAULT_MIDI_B_ROOT,
    DEFAULT_SYNTHETIC_VALIDATION,
    OFFICIAL_VALIDATOR_DIR,
)
from prototyping.midi_b.score_official import ensure_validator

# README smoke5 PatientIDs (Synthetic Validation).
SMOKE5_PATIENT_IDS: tuple[str, ...] = (
    "1011144680",
    "105230877",
    "1055270895",
    "1132133087",
    "1163484890",
)

_HERE = Path(__file__).resolve().parent
SMOKE_FLOORS_PATH = _HERE / "smoke_floors.json"
TAXONOMY_BASELINE_PATH = _HERE / "taxonomy_baseline.json"
NER_ADVERSARIAL_JSONL = (
    Path(__file__).resolve().parents[2] / "fixtures" / "phi_text" / "midi_b_ner_adversarial.jsonl"
)


def midi_b_ready() -> bool:
    """True when Synthetic Validation tree and answer key DB exist."""
    return (
        DEFAULT_MIDI_B_ROOT.is_dir()
        and DEFAULT_SYNTHETIC_VALIDATION.is_dir()
        and DEFAULT_ANSWER_KEY_VALIDATION.is_file()
    )


def validator_ready() -> bool:
    """True when the official CBIIT MIDI_validation_script is present."""
    try:
        ensure_validator(OFFICIAL_VALIDATOR_DIR)
    except FileNotFoundError:
        return False
    return True


def midi_b_python_deps_ready() -> bool:
    """True when the midi-b dependency group is installed (nltk for official score)."""
    try:
        import nltk  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


def write_baseline_enabled() -> bool:
    """True when MIDI_B_WRITE_BASELINE is set to a truthy value."""
    return os.environ.get("MIDI_B_WRITE_BASELINE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def full_validation_enabled() -> bool:
    """True when MIDI_B_FULL requests the overnight full Validation gate."""
    return os.environ.get("MIDI_B_FULL", "").strip().lower() in {"1", "true", "yes"}


def load_json(path: Path) -> dict:
    """Load a JSON object from path."""
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    """Write pretty JSON with trailing newline."""
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
