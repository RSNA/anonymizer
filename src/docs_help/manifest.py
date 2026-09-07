"""Load docs/screenshots-manifest.yaml for MkDocs help screenshot capture."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO_ROOT / "docs" / "screenshots-manifest.yaml"


@dataclass(frozen=True)
class ShotSpec:
    id: str
    file: str
    window: str
    severity: str
    deps: tuple[str, ...] = ()
    ux_elements: tuple[str, ...] = ()
    caption: str = ""
    recipe: dict[str, Any] = field(default_factory=dict)
    workflow_id: str = ""
    shots_dir: str = "shots"

    @property
    def soft(self) -> bool:
        return self.severity == "soft"

    @property
    def orthanc(self) -> bool:
        return self.severity == "orthanc"


@dataclass(frozen=True)
class WorkflowSpec:
    id: str
    doc: str
    title: str
    shots_dir: str
    shots: tuple[ShotSpec, ...]


@dataclass(frozen=True)
class Manifest:
    fixtures: dict[str, Path]
    languages: dict[str, str]
    orthanc: dict[str, Any]
    workflows: tuple[WorkflowSpec, ...]

    def all_shots(self) -> list[ShotSpec]:
        out: list[ShotSpec] = []
        for wf in self.workflows:
            out.extend(wf.shots)
        return out

    def shot_by_id(self, shot_id: str) -> ShotSpec | None:
        for shot in self.all_shots():
            if shot.id == shot_id:
                return shot
        return None

    def output_path(self, language_code: str, shot: ShotSpec, *, capture_os: str = "macos") -> Path:
        """PNG path under ``docs/<lang>/<workflow>/shots/<os>/<file>``."""
        lang_dir = self.languages[language_code]
        return (
            REPO_ROOT
            / "docs"
            / lang_dir
            / shot.workflow_id
            / shot.shots_dir
            / capture_os
            / shot.file
        )


def load_manifest(path: Path | None = None) -> Manifest:
    manifest_path = path or DEFAULT_MANIFEST
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    fixtures = {k: REPO_ROOT / v for k, v in (data.get("fixtures") or {}).items()}
    languages = dict(data.get("languages") or {})
    orthanc = dict(data.get("orthanc") or {})
    workflows: list[WorkflowSpec] = []
    for wf in data.get("workflows") or []:
        shots: list[ShotSpec] = []
        for raw in wf.get("shots") or []:
            shots.append(
                ShotSpec(
                    id=raw["id"],
                    file=raw["file"],
                    window=raw.get("window", ""),
                    severity=raw.get("severity", "required"),
                    deps=tuple(raw.get("deps") or ()),
                    ux_elements=tuple(raw.get("ux_elements") or ()),
                    caption=str(raw.get("caption") or ""),
                    recipe=dict(raw.get("recipe") or {}),
                    workflow_id=wf["id"],
                    shots_dir=wf.get("shots_dir", "shots"),
                )
            )
        workflows.append(
            WorkflowSpec(
                id=wf["id"],
                doc=wf.get("doc", ""),
                title=wf.get("title", wf["id"]),
                shots_dir=wf.get("shots_dir", "shots"),
                shots=tuple(shots),
            )
        )
    return Manifest(
        fixtures=fixtures,
        languages=languages,
        orthanc=orthanc,
        workflows=tuple(workflows),
    )
