"""Invoke CBIIT MIDI_validation_script against anonymized store + mappings."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from eval.midi_b.paths import OFFICIAL_VALIDATOR_DIR

logger = logging.getLogger(__name__)


def ensure_validator(validator_dir: Path | None = None) -> Path:
    """
    Resolve the official validator checkout.

    Args:
        validator_dir: Optional override of the vendor clone path.

    Returns:
        Path to the validator root containing run_validation.py.

    Raises:
        FileNotFoundError: When the validator is missing.
    """
    root = Path(validator_dir or OFFICIAL_VALIDATOR_DIR)
    run_py = root / "run_validation.py"
    if not run_py.is_file():
        raise FileNotFoundError(
            f"official MIDI validator not found at {run_py}; "
            "clone https://github.com/CBIIT/MIDI_validation_script into "
            f"{OFFICIAL_VALIDATOR_DIR}"
        )
    return root


def write_config(
    *,
    run_name: str,
    input_data_path: Path,
    output_data_path: Path,
    answer_db_file: Path,
    uid_mapping_file: Path,
    patid_mapping_file: Path,
    config_path: Path,
    multiprocessing: bool = False,
    multiprocessing_cpus: int = 4,
    log_level: str = "info",
) -> Path:
    """
    Write official config.json for the CBIIT validator.

    Args:
        run_name: Scorer run label.
        input_data_path: Anonymized DICOM store root.
        output_data_path: Directory for official score artifacts.
        answer_db_file: Answer-key SQLite path.
        uid_mapping_file: UID mapping CSV.
        patid_mapping_file: Patient-ID mapping CSV.
        config_path: Destination config.json.
        multiprocessing: Enable scorer multiprocessing.
        multiprocessing_cpus: CPU count when multiprocessing is on.
        log_level: Scorer log level string.

    Returns:
        Path to the written config file.
    """
    output_data_path.mkdir(parents=True, exist_ok=True)
    log_path = output_data_path / "logs"
    log_path.mkdir(parents=True, exist_ok=True)
    cfg = {
        "run_name": run_name,
        "input_data_path": str(input_data_path.resolve()),
        "output_data_path": str(output_data_path.resolve()),
        "answer_db_file": str(answer_db_file.resolve()),
        "uid_mapping_file": str(uid_mapping_file.resolve()),
        "patid_mapping_file": str(patid_mapping_file.resolve()),
        "multiprocessing": "True" if multiprocessing else "False",
        "multiprocessing_cpus": str(multiprocessing_cpus),
        "log_path": str(log_path.resolve()),
        "log_level": log_level,
        "report_series": "False",
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return config_path


def _run_script(script: Path, config_path: Path, *, cwd: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(cwd) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    cmd = [sys.executable, str(script.resolve()), str(config_path.resolve())]
    logger.info("running %s", " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd), env=env, check=True)


def run_validation(
    config_path: Path,
    *,
    validator_dir: Path | None = None,
    reports: bool = True,
) -> Path:
    """
    Run official validation (and optional reports) for a config.json.

    Args:
        config_path: Path to official config.json.
        validator_dir: Optional vendor root override.
        reports: Also run run_reports.py when present.

    Returns:
        Validator root path used.
    """
    root = ensure_validator(validator_dir)
    _run_script(root / "run_validation.py", config_path, cwd=root)
    if reports:
        reports_py = root / "run_reports.py"
        if reports_py.is_file():
            _run_script(reports_py, config_path, cwd=root)
    return root


def copy_score_summary(run_dir: Path, official_output: Path) -> None:
    """
    Copy official_summary.json into the run root when present.

    Args:
        run_dir: Harness run directory.
        official_output: Scorer output_data_path.
    """
    for name in ("official_summary.json", "summary.json"):
        src = official_output / name
        if src.is_file():
            shutil.copy2(src, run_dir / "official_summary.json")
            return
