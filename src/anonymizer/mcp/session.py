"""MCP project session — owns at most one headless ProjectController."""

import logging
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from anonymizer.controller.headless import create_headless_controller
from anonymizer.controller.jobs.runner import RemovePixelPhiRunner
from anonymizer.controller.project import ProjectController
from anonymizer.controller.script.paths import packaged_default_script_path
from anonymizer.model.project import ProjectModel

logger = logging.getLogger(__name__)


class ProjectSessionError(Exception):
    """Raised when an MCP project session cannot be opened or created."""


# Backward-compatible alias used by ops / older call sites.
HeadlessSessionError = ProjectSessionError


def _required_packaged_script_path() -> Path:
    """Packaged default script path, or ProjectSessionError if missing."""
    try:
        return packaged_default_script_path(require_exists=True)
    except FileNotFoundError as exc:
        raise ProjectSessionError(str(exc)) from exc


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
    """Open an existing project via create_headless_controller."""
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

    model = ProjectModel()
    model.project_name = name
    model.storage_dir = storage
    model.anonymizer_script_path = _required_packaged_script_path()
    if site_id is not None and site_id.strip():
        model.site_id = site_id.strip()
    if uid_root is not None and uid_root.strip():
        model.uid_root = uid_root.strip()
    return create_controller_from_model(model, overwrite=overwrite)


def create_controller_from_model(
    model: ProjectModel,
    *,
    overwrite: bool = False,
) -> ProjectController:
    """
    Create a project on disk from an already-built core ProjectModel.

    Args:
        model: Complete project model to persist.
        overwrite: Whether an existing project at the model storage directory
            may be replaced.

    Returns:
        Controller for the newly created project.

    Raises:
        ProjectSessionError: If the model has no name, the destination exists
            without overwrite, or project creation fails.
    """
    storage = Path(model.storage_dir).expanduser().resolve()
    if not str(model.project_name or "").strip():
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
    model.storage_dir = storage
    model.anonymizer_script_path = _required_packaged_script_path()

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
        # Temporary MCP transaction state only: an unsaved core ProjectModel
        # awaiting clinician confirmation. It is never persisted as a project
        # setting and does not gate import/PACS operations.
        self._pending_project: ProjectModel | None = None
        self._pending_revision: int = 0
        self._pending_supplied_fields: set[str] = set()
        self._pending_overwrite: bool = False
        # Background jobs for long-running batch/AI tools: one at a time,
        # polled by the client via job_status. Completed results are kept
        # (bounded) so a client that polls late still gets its result.
        self._jobs: dict[str, dict[str, Any]] = {}
        self._jobs_lock = threading.Lock()
        self._job_seq = 0

    @property
    def controller(self) -> ProjectController:
        if self._controller is None:
            raise ProjectSessionError("No project open. Call create_project or project_open first.")
        return self._controller

    @property
    def is_open(self) -> bool:
        return self._controller is not None

    @property
    def pending_project(self) -> ProjectModel | None:
        """Unsaved ProjectModel awaiting confirmation, if any."""
        return self._pending_project

    @property
    def pending_revision(self) -> int | None:
        """Current pending-project revision, or None when no draft exists."""
        return self._pending_revision if self._pending_project is not None else None

    @property
    def pending_supplied_fields(self) -> frozenset[str]:
        """ProjectModel field names explicitly supplied for the pending project."""
        return frozenset(self._pending_supplied_fields)

    @property
    def pending_overwrite(self) -> bool:
        """Whether confirming the pending project may replace an existing one."""
        return bool(self._pending_project is not None and self._pending_overwrite)

    def stage_pending_project(
        self,
        model: ProjectModel,
        *,
        supplied_fields: set[str],
        overwrite: bool,
    ) -> int:
        """
        Store an unsaved project configuration for clinician confirmation.

        Args:
            model: Complete validated core ProjectModel.
            supplied_fields: Model field names explicitly supplied by the user.
            overwrite: Whether confirmation may replace an existing project.

        Returns:
            The new pending-configuration revision.
        """
        self._pending_project = model
        self._pending_supplied_fields = set(supplied_fields)
        self._pending_overwrite = bool(overwrite)
        self._pending_revision += 1
        return self._pending_revision

    def clear_pending_project(self) -> None:
        """Discard any unsaved project configuration awaiting confirmation."""
        self._pending_project = None
        self._pending_revision = 0
        self._pending_supplied_fields = set()
        self._pending_overwrite = False

    def pending_creation(self, revision: int | None) -> tuple[ProjectModel, bool]:
        """
        Return the pending model/overwrite pair for one exact revision.

        Args:
            revision: Revision previously returned to the clinician.

        Returns:
            (model, overwrite) for the pending project.

        Raises:
            ProjectSessionError: If no draft exists or the revision is stale.
        """
        if self._pending_project is None:
            raise ProjectSessionError(
                "No pending project configuration. Call create_project with confirm=false first."
            )
        if revision is None or int(revision) != self._pending_revision:
            raise ProjectSessionError(
                "Stale or missing revision: confirm the latest pending configuration "
                f"revision {self._pending_revision}."
            )
        return self._pending_project, self._pending_overwrite

    def start_job(
        self,
        operation: str,
        work: Callable[[Callable[[float, "float | None", "str | None"], None]], dict[str, Any]],
    ) -> str:
        """
        Run work on a background thread as the session's one active job.

        Args:
            operation: Tool name the job belongs to (for status reporting).
            work: Callable receiving a progress callback and returning the
                tool result dict. Runs off the request thread so the initial
                tool call can return pending immediately.

        Returns:
            The new job id (job-N).

        Raises:
            ProjectSessionError: If another job is still running.
        """
        with self._jobs_lock:
            running = [j for j in self._jobs.values() if j["status"] == "running"]
            if running:
                active = running[0]
                raise ProjectSessionError(
                    f"Another operation is still running ({active['operation']}, "
                    f"{active['job_id']}). Poll job_status for it instead of "
                    "starting a duplicate."
                )
            self._job_seq += 1
            job_id = f"job-{self._job_seq}"
            self._jobs[job_id] = {
                "job_id": job_id,
                "operation": operation,
                "status": "running",
                "progress": {"current": 0, "total": None, "message": "starting"},
                "result": None,
                "error": None,
                "started_at": time.time(),
                "finished_at": None,
            }
            # Bound retained history: keep the newest few finished jobs.
            finished = [k for k, j in self._jobs.items() if j["status"] != "running"]
            for old_id in finished[:-5]:
                self._jobs.pop(old_id, None)

        def _progress(current: float, total: float | None, message: str | None) -> None:
            with self._jobs_lock:
                job = self._jobs.get(job_id)
                if job is not None:
                    job["progress"] = {
                        "current": current,
                        "total": total,
                        "message": message,
                    }

        def _run() -> None:
            try:
                result = work(_progress)
            except Exception as exc:  # surfaced to the client via job_status
                logger.exception("Background job %s (%s) failed", job_id, operation)
                with self._jobs_lock:
                    job = self._jobs[job_id]
                    job["status"] = "failed"
                    job["error"] = str(exc)
                    job["finished_at"] = time.time()
                return
            with self._jobs_lock:
                job = self._jobs[job_id]
                job["status"] = "completed"
                job["result"] = result
                job["finished_at"] = time.time()

        threading.Thread(target=_run, name=f"mcp-{operation}", daemon=True).start()
        return job_id

    def job_status(self, job_id: str) -> dict[str, Any]:
        """
        Return a snapshot of one background job for client polling.

        Args:
            job_id: Id previously returned with a pending tool result.

        Returns:
            Job record copy including status, progress, and the result or
            error once finished.

        Raises:
            ProjectSessionError: If the job id is unknown.
        """
        with self._jobs_lock:
            job = self._jobs.get(str(job_id or "").strip())
            if job is None:
                raise ProjectSessionError(
                    f"Unknown job_id {job_id!r}. Use the job_id returned with "
                    "the pending result."
                )
            snapshot = dict(job)
            snapshot["progress"] = dict(job["progress"])
            finished_at = job["finished_at"] or time.time()
            snapshot["elapsed_seconds"] = round(finished_at - job["started_at"], 1)
            return snapshot

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
        self.clear_pending_project()
        if self._controller is None:
            return
        ctrl = self._controller
        self._controller = None
        shutdown_controller(ctrl)

    def open_path(self, project_path: str | Path) -> ProjectController:
        """Open an existing project and discard any pending create draft."""
        self.close()
        controller = open_controller(project_path)
        self._controller = controller
        logger.info("MCP session opened project at %s", project_path)
        return controller

    def create_from_model(
        self,
        model: ProjectModel,
        *,
        overwrite: bool = False,
    ) -> ProjectController:
        """
        Persist/open a project from a complete core ProjectModel.

        Args:
            model: Project model to create.
            overwrite: Whether an existing destination project may be replaced.

        Returns:
            Controller for the created project.
        """
        if self._controller is not None:
            ctrl = self._controller
            self._controller = None
            shutdown_controller(ctrl)
        controller = create_controller_from_model(model, overwrite=overwrite)
        self._controller = controller
        self.clear_pending_project()
        logger.info(
            "MCP session created project %r at %s", model.project_name, model.storage_dir
        )
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
        """Create/open a project from identity fields and model defaults."""
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

