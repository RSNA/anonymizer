"""Defaults for Validation / Test synthetic roots and answer keys."""

from __future__ import annotations

from eval.midi_b.paths import (
    DEFAULT_ANSWER_KEY_TEST,
    DEFAULT_ANSWER_KEY_VALIDATION,
    DEFAULT_SYNTHETIC_TEST,
    DEFAULT_SYNTHETIC_VALIDATION,
    split_paths,
)


def test_split_paths_validation() -> None:
    synthetic, answer = split_paths("validation")
    assert synthetic == DEFAULT_SYNTHETIC_VALIDATION
    assert answer == DEFAULT_ANSWER_KEY_VALIDATION


def test_split_paths_test_includes_answer_key() -> None:
    synthetic, answer = split_paths("test")
    assert synthetic == DEFAULT_SYNTHETIC_TEST
    assert answer == DEFAULT_ANSWER_KEY_TEST
    assert answer is not None
    assert answer.name == "MIDI-B-Answer-Key-Test.db"
