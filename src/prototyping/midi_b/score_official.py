"""Invoke CBIIT ``MIDI_validation_script`` against our candidates + mappings."""

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from prototyping.midi_b.paths import OFFICIAL_VALIDATOR_DIR

logger = logging.getLogger(__name__)


def ensure_validator(validator_dir: Path | None = None) -> Path:
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
    """Write official ``config.json`` (paths as strings)."""
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
    # Official package imports ``modules.*`` from its own root.
    env["PYTHONPATH"] = str(cwd) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    # Absolute config path — subprocess cwd is the vendor tree.
    cmd = [sys.executable, str(script.resolve()), str(config_path.resolve())]
    logger.info("running %s", " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd), env=env, check=True)


def run_validation(
    config_path: Path,
    *,
    validator_dir: Path | None = None,
    reports: bool = True,
) -> Path:
    """Run ``run_validation.py`` (+ optional ``run_reports.py``). Returns score dir."""
    root = ensure_validator(validator_dir)
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    score_dir = Path(cfg["output_data_path"]) / cfg["run_name"]

    # Official curation_validator imports nltk; fail fast with an install hint.
    try:
        import nltk
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "nltk is required for the official MIDI scorer. "
            "Install with: uv sync --group midi-b"
        ) from exc
    try:
        nltk.download("stopwords", quiet=True)
        nltk.download("punkt", quiet=True)
        nltk.download("punkt_tab", quiet=True)
    except Exception:
        logger.warning("nltk corpus download failed; official scorer may error", exc_info=True)

    _run_script(root / "run_validation.py", config_path, cwd=root)
    if reports and (root / "run_reports.py").is_file():
        try:
            _run_script(root / "run_reports.py", config_path, cwd=root)
        except subprocess.CalledProcessError:
            logger.exception("run_reports.py failed (validation DB may still be usable)")
    return score_dir


def summarize_score_dir(score_dir: Path) -> dict:
    """Best-effort summary from official report artifacts."""
    summary: dict = {"score_dir": str(score_dir)}
    for name in (
        "scoring_report_instance.xlsx",
        "scoring_report_series.xlsx",
        "discrepancy_report.xlsx",
        "pixel_validation.xlsx",
        "validation_results.db",
    ):
        p = score_dir / name
        if p.is_file():
            summary[name] = str(p)
    summary["artifacts"] = sorted(
        str(p.relative_to(score_dir)) for p in score_dir.rglob("*") if p.is_file()
    )[:40]
    return summary


def copy_score_summary(score_dir: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = summarize_score_dir(score_dir)
    dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    for name in (
        "scoring_report_instance.xlsx",
        "scoring_report_series.xlsx",
        "discrepancy_report.xlsx",
        "pixel_validation.xlsx",
    ):
        src = score_dir / name
        if src.is_file():
            shutil.copy2(src, dest.parent / name)
    return dest
