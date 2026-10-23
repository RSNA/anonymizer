"""Headless project loading (no GUI, no MCP) shared by the CLI and MCP session.

Public API
----------
load_model(json_filepath: Path) -> ProjectModel
    Load model.

create_headless_controller(project_model_path: Path) -> ProjectController | None
    Create headless controller.
"""
import logging
import os
from pathlib import Path

from anonymizer.controller.project import ProjectController
from anonymizer.model.project import ProjectModel
from anonymizer.utils.translate import _

logger = logging.getLogger()  # ROOT logger


def load_model(json_filepath: Path) -> ProjectModel:
    try:
        with open(json_filepath, "r") as f:
            file_model = ProjectModel.from_json(f.read())  # type: ignore
        if not isinstance(file_model, ProjectModel):
            raise TypeError("Loaded object is not an instance of ProjectModel")
        logger.info(f"Project Model successfully loaded from: {json_filepath}")
        return file_model
    except Exception as e1:
        # Attempt to load backup file
        backup_filepath = str(json_filepath) + ".bak"
        if os.path.exists(backup_filepath):
            try:
                with open(backup_filepath, "r") as f:
                    file_model = ProjectModel.from_json(f.read())  # type: ignore
                if not isinstance(file_model, ProjectModel):
                    raise TypeError("Loaded backup object is not an instance of ProjectModel")
                logger.warning(f"Loaded Project Model from backup file: {backup_filepath}")
                return file_model
            except Exception as e2:
                logger.error(f"Backup Project Model datafile corrupt: {e2}")
                raise RuntimeError(f"Project datafile: {backup_filepath} and backup file corrupt\n\n{str(e2)}") from e2
        else:
            logger.error(f"Project Model datafile corrupt: {e1}")
            raise RuntimeError(f"Project Model datafile: {json_filepath} corrupt\n\n{str(e1)}") from e1


def create_headless_controller(project_model_path: Path) -> ProjectController | None:
    if not project_model_path.exists():
        logger.error(_("Project Model file not found") + f": {project_model_path}")
        return None

    if not project_model_path.is_file():
        logger.error(_("Project Model path is not a file") + f": {project_model_path}")
        return None

    try:
        file_model = load_model(project_model_path)
    except Exception as e:
        logger.error(f"Error loading Project Model: {str(e)}")
        return None

    logger.info(f"Project Model succesfully loaded from: {project_model_path}")

    if not hasattr(file_model, "version"):
        logger.error("Project Model missing version")
        return None

    logger.info(_("Project Model loaded successfully, version") + f": {file_model.version}")

    if file_model.version != ProjectModel.MODEL_VERSION:
        logger.info(
            _("Project Model version mismatch")
            + f": {file_model.version} != {ProjectModel.MODEL_VERSION} "
            + _("upgrading accordingly")
        )
        model = ProjectModel()
        model.__dict__.update(file_model.__dict__)
        model.version = ProjectModel.MODEL_VERSION
    else:
        model = file_model

    try:
        controller = ProjectController(model)
        if not controller:
            raise RuntimeError(_("Fatal Internal Error, Project Controller not created"))

        if file_model.version != ProjectModel.MODEL_VERSION:
            controller.save_model()
            logger.info(_("Project Model upgraded successfully to version" + f": {controller.model.version}"))

    except Exception as e:
        logger.error(f"Error creating Project Controller: {str(e)}")
        return None

    return controller
