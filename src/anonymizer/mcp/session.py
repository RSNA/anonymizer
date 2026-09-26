"""MCP project session — owns at most one headless ProjectController."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from anonymizer.anonymizer import create_headless_controller
from anonymizer.controller.project import ProjectController
from anonymizer.model.project import ProjectModel

logger = logging.getLogger(__name__)


class ProjectSessionError(Exception):
    """Raised when an MCP project session cannot be opened or created."""


# Backward-compatible alias used by ops / older call sites.
HeadlessSessionError = ProjectSessionError


_PACKAGED_DEFAULT_SCRIPT = (
    Path(__file__).resolve().parents[1] / "assets" / "scripts" / "default-anonymizer.script"
)


def packaged_default_script_path() -> Path:
    """Absolute path to the shipped default anonymizer script."""
    if not _PACKAGED_DEFAULT_SCRIPT.is_file():
        raise ProjectSessionError(f"Packaged anonymizer script missing: {_PACKAGED_DEFAULT_SCRIPT}")
    return _PACKAGED_DEFAULT_SCRIPT


def resolve_project_model_path(project_path: Path) -> Path:
    """Accept either ProjectModel.json or a storage directory containing it."""
    path = project_path.expanduser().resolve()
    if path.is_file():
        if path.name != ProjectController.PROJECT_MODEL_FILENAME_JSON:
            raise ProjectSessionError(
                f"Expected {ProjectController.PROJECT_MODEL_FILENAME_JSON}, got {path.name}"
            )
        return path
    if path.is_dir():
        model_path = path / ProjectController.PROJECT_MODEL_FILENAME_JSON
        if not model_path.is_file():
            raise ProjectSessionError(f"No {ProjectController.PROJECT_MODEL_FILENAME_JSON} in {path}")
        return model_path
    raise ProjectSessionError(f"Project path does not exist: {path}")


def shutdown_controller(controller: ProjectController) -> None:
    """Shared headless teardown (SCP → AE → save → anonymizer stop)."""
    try:
        if controller.scp is not None:
            controller.stop_scp()
    except Exception:
        logger.exception("Failed to stop SCP while shutting down controller")
    try:
        controller.shutdown()
    except Exception:
        logger.exception("Failed to shutdown AE while shutting down controller")
    try:
        controller.save_model()
    except Exception:
        logger.exception("Failed to save ProjectModel while shutting down controller")
    try:
        controller.anonymizer.stop()
    except Exception:
        logger.exception("Failed to stop anonymizer while shutting down controller")


def open_controller(project_path: str | Path) -> ProjectController:
    """Open an existing project via ``create_headless_controller``."""
    model_path = resolve_project_model_path(Path(project_path))
    controller = create_headless_controller(model_path)
    if controller is None:
        raise ProjectSessionError(f"Failed to open project model: {model_path}")
    return controller


def create_controller(
    *,
    storage_dir: str | Path,
    project_name: str,
    site_id: str | None = None,
    uid_root: str | None = None,
    overwrite: bool = False,
) -> ProjectController:
    """Create a new empty project on disk and return its controller."""
    storage = Path(storage_dir).expanduser().resolve()
    name = project_name.strip()
    if not name:
        raise ProjectSessionError("project_name is required")

    model_path = storage / ProjectController.PROJECT_MODEL_FILENAME_JSON
    if storage.exists() and model_path.exists():
        if not overwrite:
            raise ProjectSessionError(
                f"Project already exists at {storage}. Pass overwrite=true to replace it."
            )
        shutil.rmtree(storage)
        logger.info("Deleted existing project directory for overwrite: %s", storage)

    storage.mkdir(parents=True, exist_ok=True)

    model = ProjectModel()
    model.project_name = name
    model.storage_dir = storage
    model.anonymizer_script_path = packaged_default_script_path()
    if site_id is not None and site_id.strip():
        model.site_id = site_id.strip()
    if uid_root is not None and uid_root.strip():
        model.uid_root = uid_root.strip()

    try:
        controller = ProjectController(model)
        controller.save_model()
    except Exception as exc:
        raise ProjectSessionError(f"Failed to create project at {storage}: {exc}") from exc
    return controller


class ProjectSession:
    """Owns at most one headless ProjectController for the MCP process."""

    def __init__(self) -> None:
        self._controller: ProjectController | None = None
        self._ocr_runner = None
        self._ocr_handle = None

    @property
    def controller(self) -> ProjectController:
        if self._controller is None:
            raise ProjectSessionError("No project open. Call create_project or project_open first.")
        return self._controller

    @property
    def is_open(self) -> bool:
        return self._controller is not None

    def ensure_scp(self) -> None:
        controller = self.controller
        if controller.scp is not None:
            return
        try:
            controller.start_scp()
        except Exception as exc:
            raise ProjectSessionError(f"Failed to start local DICOM SCP: {exc}") from exc

    def ensure_ocr_reader(self, runner: object | None = None) -> object:
        if self._ocr_handle is not None and getattr(self._ocr_handle, "reader", None) is not None:
            return self._ocr_handle
        from anonymizer.controller.runner import RemovePixelPhiRunner

        self._ocr_runner = runner or RemovePixelPhiRunner()
        self._ocr_handle = self._ocr_runner.enter_models()
        return self._ocr_handle

    def close(self) -> None:
        if self._ocr_handle is not None and self._ocr_runner is not None:
            try:
                self._ocr_runner.exit_models(self._ocr_handle)
            except Exception:
                logger.exception("Failed to release OCR reader while closing session")
            self._ocr_handle = None
            self._ocr_runner = None
        if self._controller is None:
            return
        ctrl = self._controller
        self._controller = None
        shutdown_controller(ctrl)

    def open_path(self, project_path: str | Path) -> ProjectController:
        self.close()
        controller = open_controller(project_path)
        self._controller = controller
        logger.info("MCP session opened project at %s", project_path)
        return controller

    def create(
        self,
        *,
        storage_dir: str | Path,
        project_name: str,
        site_id: str | None = None,
        uid_root: str | None = None,
        overwrite: bool = False,
    ) -> ProjectController:
        self.close()
        controller = create_controller(
            storage_dir=storage_dir,
            project_name=project_name,
            site_id=site_id,
            uid_root=uid_root,
            overwrite=overwrite,
        )
        self._controller = controller
        logger.info("MCP session created project %r at %s", project_name, storage_dir)
        return controller


# Alias kept for ops signatures that still say HeadlessProjectSession.
HeadlessProjectSession = ProjectSession

SESSION = ProjectSession()

__all__ = [
    "SESSION",
    "ProjectSession",
    "ProjectSessionError",
    "HeadlessProjectSession",
    "HeadlessSessionError",
    "packaged_default_script_path",
    "resolve_project_model_path",
    "shutdown_controller",
    "open_controller",
    "create_controller",
]
