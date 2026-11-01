"""NER compile format must match Tag Name: value. lines from real DICOM metadata.

These fixtures would have failed when compile glued all values into one string
without field names or newlines.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydicom import dcmread

from anonymizer.controller.ai.embedded_phi.metadata.extract import (
    NER_INPUT_VRS,
    extract_metadata_phi_rows,
)
from anonymizer.controller.ai.embedded_phi.metadata.ner_compile import (
    NerCompileCell,
    compile_ner_input,
)
from anonymizer.controller.ai.embedded_phi.ner.radiology_filters import is_anon_identity_tag

_TEST_DCM_ROOT = (
    Path(__file__).resolve().parents[3] / "assets" / "test_dcm_files"
)
_LINE_RE = re.compile(r"^.+: .+\.$")


def _compile_cells_from_ds(ds) -> list[NerCompileCell]:
    """Mirror Clean Descriptors collect: text / impure IS-DS, skip identity tags."""
    cells: list[NerCompileCell] = []
    seen: set[str] = set()
    for row in extract_metadata_phi_rows(ds):
        if row.is_seq_text or row.is_date or row.is_anonymizer_field:
            continue
        if is_anon_identity_tag(
            tag_path=row.tag_path, tag=row.tag, field_name=row.name
        ):
            continue
        vr = str(row.vr or "").upper()
        if vr not in NER_INPUT_VRS:
            continue
        text = str(row.text or "")
        if not any(ch.isalnum() for ch in text):
            continue
        if text in seen:
            continue
        seen.add(text)
        cells.append(
            NerCompileCell(
                text=text,
                field_name=str(row.name or "").strip() or "field",
                tag=row.tag,
                vr=vr,
                tag_path=str(row.tag_path or row.tag or row.name),
            )
        )
    return cells


@pytest.mark.parametrize(
    ("rel_path", "must_contain_line"),
    [
        (
            "CT_Head_Without_Contrast_Sagittal/IM-0001-0001.dcm",
            "Series Description: Head  Sagittal CECT/Sagittal 5.0.",
        ),
        (
            "CT_Head_Without_Contrast_Sagittal/IM-0001-0001.dcm",
            "Protocol Name: Brain HCT 5mm.",
        ),
        (
            "CT_Head_Without_Contrast_Sagittal/IM-0001-0001.dcm",
            "Referring Physician's Name: ROBERTSON^GORDON^^^.",
        ),
        (
            "us_rgb_single_frame/US_RGB_SingleFrame.dcm",
            "Study Description: USS ABDOMEN.",
        ),
        (
            "synthetic_CT_chest/slice_001.dcm",
            "Series Description: Synthetic chest CT phantom.",
        ),
    ],
    ids=[
        "ct_head_series_description",
        "ct_head_protocol_name",
        "ct_head_referring_physician",
        "us_study_description",
        "synthetic_chest_series_description",
    ],
)
def test_ner_compile_lines_from_test_dcm(rel_path: str, must_contain_line: str) -> None:
    """Each descriptor is Tag Name: value. — never a glued blob."""
    path = _TEST_DCM_ROOT / rel_path
    assert path.is_file(), f"Missing checked-in test DICOM: {path}"
    ds = dcmread(str(path), stop_before_pixels=True)
    cells = _compile_cells_from_ds(ds)
    assert cells, f"expected NER cells from {rel_path}"
    compiled = compile_ner_input(cells)
    assert "\n" in compiled.ner_text, (
        "NER input must separate tags with newlines; got a single glued string"
    )
    lines = compiled.ner_text.split("\n")
    assert len(lines) >= 2
    for line in lines:
        assert _LINE_RE.fullmatch(line), (
            f"expected 'Tag Name: value.' line, got {line!r}"
        )
    assert must_contain_line in lines, (
        f"missing {must_contain_line!r} in:\n" + "\n".join(lines)
    )
    assert len(compiled.offset_map) == len(compiled.ner_text)


def test_ner_compile_rejects_glued_alnum_blob_shape() -> None:
    """Regression: glued alnum-only concat without Tag Name: wraps must fail."""
    path = _TEST_DCM_ROOT / "CT_Head_Without_Contrast_Sagittal/IM-0001-0001.dcm"
    ds = dcmread(str(path), stop_before_pixels=True)
    compiled = compile_ner_input(_compile_cells_from_ds(ds))
    # Old broken shape was one isalnum() string with no separators.
    assert not compiled.ner_text.isalnum()
    assert ": " in compiled.ner_text
    assert compiled.ner_text.count("\n") >= 1
