"""One-shot headless import and MIDI mapping export.

Public API
----------
write_uid_mapping(model, path) -> int
    Write bare id_old,id_new UID CSV for the official MIDI scorer.

write_patid_mapping(model, path) -> int
    Write bare id_old,id_new patient-ID CSV for the official MIDI scorer.

export_midi_mappings(controller, output_dir) -> dict[str, str]
    Write both mapping CSVs and a small manifest.json under output_dir.

run_headless_import(project_model_path, import_dir, *, export_mappings_dir=None) -> int
    Load project, apply stored de-identification options, import a DICOM folder, exit code.
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

from sqlalchemy import select

from anonymizer.controller.headless import create_headless_controller
from anonymizer.controller.project import ProjectController
from anonymizer.mcp.ops import HeadlessOpsError, import_directory
from anonymizer.model.anonymizer import PHI, UID, AnonymizerModel

logger = logging.getLogger(__name__)


def write_uid_mapping(model: AnonymizerModel, path: Path) -> int:
    """
    Dump the UID table as bare id_old,id_new CSV.

    Args:
        model: Anonymizer persistence model.
        path: Destination CSV path.

    Returns:
        Number of mapping rows written (excluding header).
    """
    rows = model.session.execute(select(UID.phi_uid, UID.anon_uid)).all()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["id_old", "id_new"])
        count = 0
        for phi_uid, anon_uid in rows:
            old = str(phi_uid or "").strip()
            new = str(anon_uid or "").strip()
            if not old or not new:
                continue
            writer.writerow([old, new])
            count += 1
    logger.info("wrote %d uid mappings → %s", count, path)
    return count


def write_patid_mapping(model: AnonymizerModel, path: Path) -> int:
    """
    Dump PHI patient_id → anon_patient_id as bare id_old,id_new CSV.

    Args:
        model: Anonymizer persistence model.
        path: Destination CSV path.

    Returns:
        Number of mapping rows written (excluding header).
    """
    rows = model.session.execute(select(PHI.patient_id, PHI.anon_patient_id)).all()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["id_old", "id_new"])
        count = 0
        for patient_id, anon_patient_id in rows:
            old = str(patient_id if patient_id is not None else "").strip()
            new = str(anon_patient_id or "").strip()
            if old == AnonymizerModel.DEFAULT_PHI_PATIENT_ID_PK_VALUE or not new:
                continue
            writer.writerow([old, new])
            count += 1
    logger.info("wrote %d patid mappings → %s", count, path)
    return count


def export_midi_mappings(controller: ProjectController, output_dir: Path) -> dict[str, str]:
    """
    Write UID and patient-ID mapping CSVs plus a manifest for scorers.

    Args:
        controller: Loaded project controller.
        output_dir: Directory for CSVs and manifest.json.

    Returns:
        Manifest fields written to disk (paths as strings).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    uid_path = output_dir / "uid_mapping.csv"
    patid_path = output_dir / "patid_mapping.csv"
    n_uid = write_uid_mapping(controller.anonymizer.model, uid_path)
    n_patid = write_patid_mapping(controller.anonymizer.model, patid_path)
    images = str(Path(controller.model.images_dir()).resolve())
    manifest = {
        "images_dir": images,
        "uid_mapping": str(uid_path.resolve()),
        "patid_mapping": str(patid_path.resolve()),
        "uid_mapping_rows": n_uid,
        "patid_mapping_rows": n_patid,
        "project_name": controller.model.project_name,
        "site_id": controller.model.site_id,
        "storage_dir": str(Path(controller.model.storage_dir).resolve()),
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)
    return manifest


def run_headless_import(
    project_model_path: Path,
    import_dir: Path,
    *,
    export_mappings_dir: Path | None = None,
) -> int:
    """
    One-shot: load project, apply de-identification options, import a DICOM folder.

    Args:
        project_model_path: Path to ProjectModel.json.
        import_dir: Directory of DICOM files to ingest.
        export_mappings_dir: Optional directory for MIDI mapping CSVs after import.

    Returns:
        Process exit code (0 success, 1 failure).
    """
    controller = create_headless_controller(project_model_path)
    if controller is None:
        return 1

    try:
        controller.apply_confidentiality_options()
        result = import_directory(controller, str(import_dir))
        logger.info(
            "import finished source=%s seen=%s succeeded=%s skipped=%s failed=%s",
            result.get("source"),
            result.get("files_seen"),
            result.get("succeeded"),
            result.get("skipped"),
            result.get("failed"),
        )
        print(json.dumps({k: result[k] for k in result if k != "project"}, indent=2), flush=True)
        if export_mappings_dir is not None:
            export_midi_mappings(controller, Path(export_mappings_dir))
        failed = int(result.get("failed") or 0)
        succeeded = int(result.get("succeeded") or 0)
        exit_code = 0 if succeeded > 0 and failed == 0 else (0 if succeeded > 0 else 1)
    except HeadlessOpsError as exc:
        logger.error("import failed: %s", exc)
        exit_code = 1
    except Exception:
        logger.exception("import failed")
        exit_code = 1
    finally:
        controller.shutdown()
        controller.save_model()
        controller.anonymizer.stop()

    return exit_code


def run_headless_export_mappings(
    project_model_path: Path,
    export_mappings_dir: Path,
) -> int:
    """
    One-shot: load project and write MIDI mapping CSVs.

    Args:
        project_model_path: Path to ProjectModel.json.
        export_mappings_dir: Directory for CSVs and manifest.json.

    Returns:
        Process exit code (0 success, 1 failure).
    """
    controller = create_headless_controller(project_model_path)
    if controller is None:
        return 1
    try:
        export_midi_mappings(controller, Path(export_mappings_dir))
        return 0
    except Exception:
        logger.exception("mapping export failed")
        return 1
    finally:
        controller.shutdown()
        controller.anonymizer.stop()
