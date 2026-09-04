#!/usr/bin/env python3
"""Cold-cache Harmonize stage timing for a single DICOM series directory.

Example (do not commit PHI paths into defaults):

  uv run python src/prototyping/benchmark_harmonize_series.py \\
    --series "/path/to/series" --label pre --dual-pass

  uv run python src/prototyping/benchmark_harmonize_series.py \\
    --series "/path/to/series" --label post
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from anonymizer.controller.ai.harmonize import HarmonizeTimingCollector, harmonize_series
from anonymizer.controller.ai.tseg.cache import clear_series_tseg_cache
from anonymizer.controller.ai.tseg.config import ENABLE_CT_HARMONIZE_SINGLE_PASS
from anonymizer.controller.ai.tseg.model_cache import tseg_batch_session


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series", type=Path, required=True, help="DICOM series directory")
    parser.add_argument("--label", default="run", help="Label embedded in JSON output")
    parser.add_argument(
        "--dual-pass",
        action="store_true",
        help="Force legacy ROI anatomy + separate contrast statistics (disable single-pass)",
    )
    parser.add_argument(
        "--keep-cache",
        action="store_true",
        help="Do not clear 0_TS_SEG before the run (warm cache)",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write timing JSON",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    series = args.series.expanduser().resolve()
    if not series.is_dir():
        print(f"Series directory not found: {series}", file=sys.stderr)
        return 2

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    import anonymizer.controller.ai.tseg.config as tseg_config

    previous = tseg_config.ENABLE_CT_HARMONIZE_SINGLE_PASS
    if args.dual_pass:
        tseg_config.ENABLE_CT_HARMONIZE_SINGLE_PASS = False
    try:
        if not args.keep_cache:
            clear_series_tseg_cache(series)
            print(f"Cleared TS cache for {series}")

        collector = HarmonizeTimingCollector()
        print(
            f"Running Harmonize ({'dual-pass' if args.dual_pass else 'single-pass'}; "
            f"flag={tseg_config.ENABLE_CT_HARMONIZE_SINGLE_PASS}) on {series}"
        )
        with tseg_batch_session(preload=True):
            results = harmonize_series([series], timing_collector=collector)
    finally:
        tseg_config.ENABLE_CT_HARMONIZE_SINGLE_PASS = previous

    timing = collector.results[0] if collector.results else None
    payload = {
        "label": args.label,
        "series": str(series),
        "dual_pass": bool(args.dual_pass),
        "enable_ct_single_pass_default": ENABLE_CT_HARMONIZE_SINGLE_PASS,
        "timing": timing.as_log_dict() if timing is not None else None,
        "result_error": results[0].error if results else "no result",
        "radlex_series_description": (results[0].radlex_series_description if results else None),
        "body_part": (results[0].playbook.body_part_code if results and results[0].playbook else None),
        "iv_contrast": (results[0].playbook.iv_contrast_code if results and results[0].playbook else None),
    }
    text = json.dumps(payload, indent=2)
    print(text)
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {args.json_out}")
    return 0 if results and results[0].error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
