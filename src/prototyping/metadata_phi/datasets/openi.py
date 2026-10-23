"""Load Open-i / Indiana University NLMCXR de-identified radiology reports."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class OpenIReport:
    id: str
    path: Path
    findings: str
    impression: str
    comparison: str
    indication: str

    @property
    def body(self) -> str:
        parts = []
        if self.indication:
            parts.append(f"INDICATION: {self.indication}")
        if self.comparison:
            parts.append(f"COMPARISON: {self.comparison}")
        if self.findings:
            parts.append(f"FINDINGS: {self.findings}")
        if self.impression:
            parts.append(f"IMPRESSION: {self.impression}")
        return "\n".join(parts)


def _text(node: ET.Element | None) -> str:
    if node is None or not (node.text or "").strip():
        return ""
    return " ".join((node.text or "").split())


def load_report(path: Path) -> OpenIReport | None:
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return None
    root = tree.getroot()
    sections: dict[str, str] = {}
    for at in root.iter():
        if at.tag.endswith("AbstractText"):
            label = (at.attrib.get("Label") or "").upper()
            if label:
                sections[label] = _text(at)
    uid = path.stem
    for u in root.iter():
        if u.tag.endswith("uId") and u.attrib.get("id"):
            uid = u.attrib["id"]
            break
    return OpenIReport(
        id=uid,
        path=path,
        findings=sections.get("FINDINGS", ""),
        impression=sections.get("IMPRESSION", ""),
        comparison=sections.get("COMPARISON", ""),
        indication=sections.get("INDICATION", ""),
    )


def iter_reports(root: str | Path, *, limit: int | None = None) -> list[OpenIReport]:
    root = Path(root)
    paths = sorted(root.glob("*.xml"))
    out: list[OpenIReport] = []
    for path in paths:
        rep = load_report(path)
        if rep is None:
            continue
        if not (rep.findings or rep.impression):
            continue
        out.append(rep)
        if limit is not None and len(out) >= limit:
            break
    return out
