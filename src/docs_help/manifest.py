"""Load docs/screenshots-manifest.yaml for MkDocs help screenshot capture."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO_ROOT / "docs" / "screenshots-manifest.yaml"

# MkDocs nav chapter numbers with shots (1, 4, 8 overview, 10 have no PNGs).
EXPECTED_CHAPTERS = ("2", "3", "5", "6", "7", "8.1", "8.2", "8.3", "8.4", "9")


def chapter_sort_key(chapter: str) -> tuple[int, ...]:
    """Numeric key so 8.2 Harmonize sorts before 9 Send (folder 03 vs 09 is irrelevant)."""
    parts: list[int] = []
    for token in str(chapter).strip().split("."):
        try:
            parts.append(int(token))
        except ValueError:
            continue
    return tuple(parts) or (0,)


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
    chapter: str = ""
    workflow_title: str = ""

    @property
    def soft(self) -> bool:
        return self.severity == "soft"

    @property
    def orthanc(self) -> bool:
        return self.severity == "orthanc"

    @property
    def chapter_label(self) -> str:
        """E.g. ``8.2 Harmonize names`` — chapter number plus title."""
        number = (self.chapter or "").strip()
        title = (self.workflow_title or "").strip()
        if number and title:
            return f"{number} {title}"
        return number or title or self.workflow_id


@dataclass(frozen=True)
class WorkflowSpec:
    id: str
    chapter: str
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

    def language_codes(self) -> tuple[str, ...]:
        """Capture language codes in manifest order (en_US, de, es, fr)."""
        return tuple(self.languages)

    def shot_by_id(self, shot_id: str) -> ShotSpec | None:
        for shot in self.all_shots():
            if shot.id == shot_id:
                return shot
        return None

    def chapter_sequence_label(self) -> str:
        return " → ".join(f"{wf.chapter} {wf.title}" for wf in self.workflows)

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
        chapter = str(wf.get("chapter") or "").strip()
        if not chapter:
            raise ValueError(f"Workflow {wf['id']!r} is missing required 'chapter' (MkDocs nav number)")
        title = str(wf.get("title") or wf["id"])
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
                    chapter=chapter,
                    workflow_title=title,
                )
            )
        workflows.append(
            WorkflowSpec(
                id=wf["id"],
                chapter=chapter,
                doc=wf.get("doc", ""),
                title=title,
                shots_dir=wf.get("shots_dir", "shots"),
                shots=tuple(shots),
            )
        )
    workflows.sort(key=lambda wf: chapter_sort_key(wf.chapter))
    return Manifest(
        fixtures=fixtures,
        languages=languages,
        orthanc=orthanc,
        workflows=tuple(workflows),
    )
