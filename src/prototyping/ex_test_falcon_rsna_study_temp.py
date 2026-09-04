#!/usr/bin/env python3
"""Backward-compatible entry point. Prefer ``prototyping.falcon.rsna_eligibility``."""

from prototyping.falcon.rsna_eligibility import run_eligibility_scan_first_10

if __name__ == "__main__":
    run_eligibility_scan_first_10()
