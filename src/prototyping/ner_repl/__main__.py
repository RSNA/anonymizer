"""Interactive OpenMed NER REPL.

Type a line and press Enter to run the token-classification pipeline.
Prints the raw Hugging Face entity dicts (entity_group / score / offsets).
Empty line or Ctrl-D / Ctrl-C exits.

Usage
-----
uv run python -m prototyping.ner_repl
"""

from __future__ import annotations

import sys
from pprint import pformat

from anonymizer.controller.ai.embedded_phi.ner.cache import (
    load_token_classification_pipeline,
    ner_ready,
    resolve_model_id,
)


def main() -> int:
    """Load OpenMed once, then loop: line → raw pipeline output."""
    if not ner_ready():
        print("NER weights not ready (download Embedded PHI models first).", file=sys.stderr)
        return 1

    model_id = resolve_model_id("en_US")
    print(f"Loading {model_id} …", file=sys.stderr)
    pipe = load_token_classification_pipeline(model_id)
    print("Ready. Enter text (empty line to quit).", file=sys.stderr)

    while True:
        try:
            line = input("> ")
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr)
            break
        if not line.strip():
            break
        try:
            raw = pipe(line)
        except Exception as exc:  # noqa: BLE001
            print(f"pipeline error: {exc}", file=sys.stderr)
            continue
        rows = []
        for ent in raw:
            row = dict(ent)
            start = int(row.get("start", 0))
            end = int(row.get("end", 0))
            row["text"] = line[start:end]
            if "score" in row:
                row["score"] = float(row["score"])
            rows.append(row)
        print(pformat(rows, sort_dicts=False))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
