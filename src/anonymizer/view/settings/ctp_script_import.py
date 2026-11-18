"""View helper: Import CTP Script from Project Settings or the script editor.

Purpose
    Shared file-pick → adapt → prompt → validate → optional install pipeline.
    Uses the same validate_document gate as AnonymizerController.reload_script.

Public API
----------
pick_ctp_script_path(parent) -> Path | None
    Open-file dialog for .script / .script.txt.

prepare_ctp_script_import(parent, source, *, project_model, ...) -> PreparedCtpImport | None
    Adapt CTP forms, prompt for params/lookup table, validate_document.

install_ctp_script_import(parent, *, project_model, project_controller, prepared) -> Path | None
    Write project script, reload keep table, record option metadata, show result.

record_imported_script_options(parent, project_model, project_controller, document) -> bool
    De-identification Options dialog (metadata only); True when codes were saved.

import_success_body(project_model, prepared, *, options_recorded) -> str
    Plain-language success text including validation passed.

run_ctp_script_import_from_settings(parent, project_model, project_controller, ...) -> bool
    Full Settings Import path; True when installed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox

from anonymizer.controller.ctp_lookup import CtpLookupPreview, lookup_table_context
from anonymizer.controller.dates import (
    DEFAULT_LONGITUDINAL_TEMPORAL_EVENT_TYPE,
    LONGITUDINAL_TEMPORAL_EVENT_TYPES,
)
from anonymizer.controller.project import ProjectController
from anonymizer.controller.script.ctp_normalize import (
    format_import_adaptation_summary,
    format_validation_errors,
    normalize_ctp_document,
    unresolved_dateinc_tags,
    unresolved_param_names,
)
from anonymizer.controller.script.date_rules import (
    apply_study_date_operation_to_rules,
    mismatched_date_rules,
)
from anonymizer.controller.script.document import (
    ScriptDocument,
    load_script_rules,
    validate_document,
    write_script_rules,
)
from anonymizer.controller.script.operands import (
    LOOKUP_TABLE_OPERANDS,
    OperandId,
    operand_id_for_operation,
    operand_spec_by_id,
)
from anonymizer.controller.script.options import infer_options_from_script
from anonymizer.model.project import ProjectModel
from anonymizer.utils.dicom import DeidMethodCode
from anonymizer.utils.translate import _
from anonymizer.view.common.busy_status_dialog import run_with_busy
from anonymizer.view.common.file_dialogs import open_filetypes

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedCtpImport:
    """Validated CTP import ready to show in the editor or install."""

    document: ScriptDocument
    warnings: list[str]
    source: Path


def pick_ctp_script_path(parent) -> Path | None:
    """
    Ask the user for a CTP anonymizer script file.

    Args:
        parent: Parent window for the file dialog.

    Returns:
        Selected path, or None when cancelled.
    """
    path = filedialog.askopenfilename(
        parent=parent,
        title=_("Import CTP Script"),
        filetypes=open_filetypes(
            (_("Script Files"), "*.script"),
            (_("Script Files"), "*.script.txt"),
        ),
    )
    if not path:
        return None
    return Path(path)


def prepare_ctp_script_import(
    parent,
    source: Path,
    *,
    project_model: ProjectModel,
    project_controller: ProjectController | None = None,
    pending_lookup_preview: CtpLookupPreview | None = None,
    on_pending_lookup_preview: Callable[[CtpLookupPreview], None] | None = None,
    on_script_path_changed: Callable[[Path], None] | None = None,
) -> PreparedCtpImport | None:
    """
    Load, adapt, prompt, and validate a CTP script.

    Args:
        parent: Parent window for busy/prompt dialogs.
        source: Path to the script file.
        project_model: Project / settings model (lookup context and staging).
        project_controller: Live controller when the project is open, else None.
        pending_lookup_preview: Create-project staged lookup preview, if any.
        on_pending_lookup_preview: Called when a new-project lookup table is staged.
        on_script_path_changed: Called when a live-project lookup commit writes the script.

    Returns:
        Prepared import, or None when cancelled or validation failed.
    """
    title = _("Import CTP Script")
    try:
        document, warnings = run_with_busy(
            parent,
            title=title,
            status=_("Reading and adapting script…"),
            work=lambda: _load_and_normalize(source),
        )
    except Exception as exc:
        messagebox.showerror(title, str(exc), parent=parent)
        return None

    if unresolved_dateinc_tags(document):
        days = _prompt_dateinc_days(parent, title)
        if days is None:
            return None
        document.params["DATEINC"] = str(int(days))
        warnings = run_with_busy(
            parent,
            title=title,
            status=_("Applying date offset…"),
            work=lambda: normalize_ctp_document(document, dateinc=int(days)),
        )

    for param_name in unresolved_param_names(document):
        text = _prompt_script_param(parent, title, param_name)
        if text is None:
            return None
        document.params[param_name] = text
        warnings = run_with_busy(
            parent,
            title=title,
            status=_("Applying script parameters…"),
            work=lambda: normalize_ctp_document(document),
        )

    try:
        errors = run_with_busy(
            parent,
            title=title,
            status=_("Checking script rules…"),
            work=lambda: validate_document(document),
        )
    except Exception as exc:
        messagebox.showerror(title, str(exc), parent=parent)
        return None
    if errors:
        messagebox.showerror(
            title,
            _("Script did not pass validation.")
            + "\n\n"
            + format_validation_errors(errors),
            parent=parent,
        )
        return None

    mismatched = mismatched_date_rules(document)
    if mismatched:
        tags = ", ".join(rule.tag.upper() for rule in mismatched[:20])
        if not messagebox.askyesno(
            title,
            _("Date rules must match the StudyDate operation.")
            + f"\n{tags}\n\n"
            + _("Apply the StudyDate operation to all date fields?"),
            parent=parent,
        ):
            return None
        apply_study_date_operation_to_rules(document)
        errors = validate_document(document)
        if errors:
            messagebox.showerror(
                title,
                _("Script did not pass validation.")
                + "\n\n"
                + format_validation_errors(errors),
                parent=parent,
            )
            return None

    if _document_uses_lookup_table(document) and not lookup_table_context(
        project_model, pending_lookup_preview
    ).present:
        if not _prompt_patient_lookup_table(
            parent,
            document=document,
            project_controller=project_controller,
            on_pending_lookup_preview=on_pending_lookup_preview,
            on_script_path_changed=on_script_path_changed,
        ):
            return None
        errors = validate_document(document)
        if errors:
            messagebox.showerror(
                title,
                _("Script did not pass validation.")
                + "\n\n"
                + format_validation_errors(errors),
                parent=parent,
            )
            return None

    return PreparedCtpImport(document=document, warnings=warnings, source=source)


def record_imported_script_options(
    parent,
    project_model: ProjectModel,
    project_controller: ProjectController | None,
    document: ScriptDocument,
) -> bool:
    """
    Open de-identification options as metadata for an imported script.

    Args:
        parent: Parent window.
        project_model: Settings or project model to update.
        project_controller: Live controller when the project is open, else None.
        document: Imported script document (for inference).

    Returns:
        True when the user OK'd and codes were stored.
    """
    # Lazy: avoid import cycle with settings dialogs that import this helper.
    from anonymizer.view.settings.deidentification_options_dialog import (  # noqa: PLC0415
        DeidentificationOptionsDialog,
    )

    inferred = infer_options_from_script(document)
    intro = (
        "These options are project metadata for the imported script "
        "(option codes used at ingest).\n\n"
        "OK saves the checkboxes only — it does not rebuild or replace the "
        "script you imported. Cancel keeps the project's previous options; "
        "the imported script stays.\n\n"
        "Later: changing de-identification options in Project Settings rebuilds "
        "the script from the packaged default and discards this import."
    )
    dlg = DeidentificationOptionsDialog(parent, inferred, intro=_(intro))
    selected = dlg.get_input()
    if selected is None:
        return False
    options = frozenset(selected) | {DeidMethodCode.BASIC}
    project_model.confidentiality_options = options
    if project_controller is not None:
        project_controller.model.confidentiality_options = options
        project_controller.save_model()
    return True


def install_ctp_script_import(
    parent,
    *,
    project_model: ProjectModel,
    project_controller: ProjectController | None,
    prepared: PreparedCtpImport,
) -> Path | None:
    """
    Install a prepared import as the project script and show the result.

    Args:
        parent: Parent window.
        project_model: Project / settings model.
        project_controller: Live controller when open, else None.
        prepared: Output of prepare_ctp_script_import.

    Returns:
        Installed script path, or None on failure.
    """
    title = _("Import CTP Script")
    storage = Path(project_model.storage_dir)
    if not str(storage).strip():
        messagebox.showerror(
            title,
            _("Set a project storage folder before importing a script."),
            parent=parent,
        )
        return None

    dest = storage / f"{project_model.site_id}-anonymizer.script"

    def _write() -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_script_rules(dest, prepared.document)
        return dest

    try:
        run_with_busy(
            parent,
            title=title,
            status=_("Installing project script…"),
            work=_write,
        )
    except Exception as exc:
        messagebox.showerror(title, str(exc), parent=parent)
        return None

    project_model.anonymizer_script_path = dest
    prepared.document.source_path = dest
    if project_controller is not None:
        try:
            run_with_busy(
                parent,
                title=title,
                status=_("Checking script rules…"),
                work=lambda: project_controller.anonymizer.reload_script(dest),
            )
            project_controller.model.anonymizer_script_path = dest
            project_controller.save_model()
        except Exception as exc:
            logger.exception("reload_script after CTP import failed")
            messagebox.showerror(
                title,
                _("Script did not pass validation.") + f"\n\n{exc}",
                parent=parent,
            )
            return None

    options_recorded = record_imported_script_options(
        parent, project_model, project_controller, prepared.document
    )
    messagebox.showinfo(
        title,
        import_success_body(
            project_model,
            prepared,
            installed_path=dest,
            options_recorded=options_recorded,
        ),
        parent=parent,
    )
    return dest


def import_success_body(
    project_model: ProjectModel,
    prepared: PreparedCtpImport,
    *,
    installed_path: Path | None,
    options_recorded: bool | None = None,
    editor_pending_accept: bool = False,
) -> str:
    """
    Build the Import success dialog body.

    Args:
        project_model: For abridged path text.
        prepared: Prepared import (warnings).
        installed_path: Project script path when already written.
        options_recorded: True/False after options dialog; None if not shown yet.
        editor_pending_accept: True when the editor still needs Accept to save.

    Returns:
        Multi-line message for showinfo.
    """
    lines = [
        _("Script imported successfully and passed validation."),
    ]
    if installed_path is not None:
        path_text = project_model.abridged_path(installed_path, include_filename=True)
        lines.append(_("Saved as the project script:") + f"\n{path_text}")
    summary = format_import_adaptation_summary(prepared.warnings)
    if summary:
        heading, *bullets = summary.splitlines()
        lines.append("")
        lines.append(_(heading))
        lines.extend(bullets)
    else:
        lines.append("")
        lines.append(_("No CTP operation adaptations were required."))
    lines.append("")
    if editor_pending_accept:
        lines.append(_("Review the Active list, then Accept to save the project script."))
    elif options_recorded is True:
        lines.append(_("De-identification option codes were recorded for this project."))
    elif options_recorded is False:
        lines.append(_("Previous de-identification option codes were kept."))
    return "\n".join(lines)


def run_ctp_script_import_from_settings(
    parent,
    project_model: ProjectModel,
    project_controller: ProjectController | None,
    *,
    pending_lookup_preview: CtpLookupPreview | None = None,
    on_pending_lookup_preview: Callable[[CtpLookupPreview], None] | None = None,
    on_script_path_changed: Callable[[Path], None] | None = None,
) -> bool:
    """
    Full Project Settings Import CTP Script flow.

    Args:
        parent: Settings dialog.
        project_model: Working model.
        project_controller: Live controller when the project exists.
        pending_lookup_preview: Create-project staged lookup preview, if any.
        on_pending_lookup_preview: Called when a new-project lookup table is staged.
        on_script_path_changed: Called when a live-project lookup commit writes the script.

    Returns:
        True when the script was installed.
    """
    source = pick_ctp_script_path(parent)
    if source is None:
        return False
    prepared = prepare_ctp_script_import(
        parent,
        source,
        project_model=project_model,
        project_controller=project_controller,
        pending_lookup_preview=pending_lookup_preview,
        on_pending_lookup_preview=on_pending_lookup_preview,
        on_script_path_changed=on_script_path_changed,
    )
    if prepared is None:
        return False
    return (
        install_ctp_script_import(
            parent,
            project_model=project_model,
            project_controller=project_controller,
            prepared=prepared,
        )
        is not None
    )


def _document_uses_lookup_table(document: ScriptDocument) -> bool:
    """True when any rule uses a lookup-table operand (same set as the script editor)."""
    return any(
        operand_id_for_operation(rule.operation) in LOOKUP_TABLE_OPERANDS
        for rule in document.rules
    )


def _prompt_patient_lookup_table(
    parent,
    *,
    document: ScriptDocument,
    project_controller: ProjectController | None,
    on_pending_lookup_preview: Callable[[CtpLookupPreview], None] | None,
    on_script_path_changed: Callable[[Path], None] | None,
) -> bool:
    """
    Open Load Patient Lookup Table; True when the user Accepts.

    Args:
        parent: Parent window (waits on the dialog).
        document: Imported script (patched in place on Accept).
        project_controller: Live controller when open, else None.
        on_pending_lookup_preview: New-project staging callback.
        on_script_path_changed: Live-project script path callback.
    """
    # Lazy: avoid import cycle with the script editor that imports this helper.
    from anonymizer.view.settings.lookup_table_dialog import LookupTableDialog  # noqa: PLC0415
    dialog = LookupTableDialog(
        parent,
        project_controller=project_controller,
        on_script_path_changed=on_script_path_changed,
        on_pending_preview=on_pending_lookup_preview if project_controller is None else None,
        script_document=document,
    )
    parent.wait_window(dialog)
    return bool(dialog.committed())


def _load_and_normalize(source: Path) -> tuple[ScriptDocument, list[str]]:
    """Worker-thread safe load + CTP normalize."""
    document = load_script_rules(source)
    warnings = normalize_ctp_document(document)
    return document, warnings


def _prompt_dateinc_days(parent, title: str) -> int | None:
    """Prompt for trial-wide day offset when DATEINC is unresolved."""
    # Lazy: OperandParamDialog lives in the script editor module.
    from anonymizer.view.settings.anonymizer_script_dialog import (  # noqa: PLC0415
        OperandParamDialog,
    )

    spec = operand_spec_by_id(OperandId.INCREMENTDATE)
    if spec is None:
        messagebox.showerror(
            title,
            _("Unsupported script:") + "\n" + "@incrementdate(this,@DATEINC)",
            parent=parent,
        )
        return None
    value = OperandParamDialog(
        parent,
        title=title,
        message=_(
            "This script uses a trial-wide date offset without a value. "
            "Enter the day offset to apply to all date fields."
        ),
        initial=-730,
        kind="int_signed",
    ).result
    if value is None:
        return None
    return int(value)


def _prompt_script_param(parent, title: str, param_name: str) -> str | None:
    """Prompt for a missing script <p> parameter (LTET gets a menu)."""
    # Lazy: OperandParamDialog lives in the script editor module.
    from anonymizer.view.settings.anonymizer_script_dialog import (  # noqa: PLC0415
        OperandParamDialog,
    )

    if param_name.upper() == "LTET":
        value = OperandParamDialog(
            parent,
            title=title,
            message=_(
                "This script stamps Longitudinal Temporal Event Type "
                "(0012,0053). Choose the event type for this project:"
            ),
            initial=DEFAULT_LONGITUDINAL_TEMPORAL_EVENT_TYPE,
            kind="choice",
            choices=LONGITUDINAL_TEMPORAL_EVENT_TYPES,
        ).result
    else:
        value = OperandParamDialog(
            parent,
            title=title,
            message=_("Enter value for script parameter {name}:").format(name=param_name),
            initial="",
            kind="str",
        ).result
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        messagebox.showerror(
            title,
            _("Script parameter {name} cannot be empty.").format(name=param_name),
            parent=parent,
        )
        return None
    return text
