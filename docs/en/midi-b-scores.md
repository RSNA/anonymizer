# MIDI-B scores

Published scores from full Synthetic Validation and Synthetic Test runs, measured with
the official MIDI validation scorer. These are **evidence for header review**, not a
HIPAA product certification — see [HIPAA Safe Harbor and MIDI-B](deidentification-protocol.md#hipaa-safe-harbor-and-midi-b).

## Current published scores

| Split | Official score | Date | Commit |
| --- | ---: | --- | --- |
| Synthetic Validation (full) | **99.03%** | 2026-11-01 | `6afbe5c` |
| Synthetic Test (full) | **99.08%** | 2026-11-01 | `6afbe5c` |

Full action tables and top failing tags:

- [Validation scorecard](https://github.com/RSNA/anonymizer/blob/dev/src/eval/midi_b/scorecards/validation_20261101_full.md)
- [Test scorecard](https://github.com/RSNA/anonymizer/blob/dev/src/eval/midi_b/scorecards/test_20261101_full.md)

Known source / answer-key mismatches that dominate most residual fails:
[source_answer_errors.md](https://github.com/RSNA/anonymizer/blob/dev/src/eval/midi_b/scorecards/source_answer_errors.md).

## How to reproduce

Harness and options: [`src/eval/midi_b/README.md`](https://github.com/RSNA/anonymizer/blob/dev/src/eval/midi_b/README.md)
in the repository (also summarized under [Run headless — MIDI-B evaluation](10-headless/index.md#midi-b-evaluation)).
Published cards live under `src/eval/midi_b/scorecards/` — copy a new `SCORECARD.md`
there when you publish a milestone; do not commit scratch run directories.
