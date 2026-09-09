"""Parse and assert SeriesView startup load traces from caplog."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pydicom import dcmread

from tests.controller.tseg.support.synthetic_ct import (
    SYNTHETIC_VOLUME_MIN_SLICES,
    build_synthetic_abdomen_ct_series,
    build_synthetic_bolus_monitor_series,
    build_synthetic_breast_adc_mr_series,
    build_synthetic_breast_mr_anatomical_series,
    build_synthetic_chest_ct_series,
    build_synthetic_coronal_ct_series,
    build_synthetic_ct_perfusion_map_series,
    build_synthetic_ct_small_series,
    build_synthetic_derived_coronal_mpr_series,
    build_synthetic_derived_mip_series,
    build_synthetic_fused_pet_ct_series,
    build_synthetic_haste_sag_series,
    build_synthetic_head_ct_series,
    build_synthetic_oblique_ct_series,
    build_synthetic_sagittal_ct_series,
    build_synthetic_scout_ct_series,
    build_synthetic_single_slice_ct_series,
    build_synthetic_survey_mr_series,
    build_synthetic_wide_ct_series,
)

TRACE_LOGGER = "anonymizer.view.series.series"
TRACE_PREFIX = "SeriesView load: "

STARTUP_STEPS = (
    "finish_loading",
    "build_ui_done",
    "startup_spec",
    "geometry_applied",
    "startup_paint",
    "startup_painted",
    "seg_chrome",
    "deiconify",
    "startup_complete",
)

FORBIDDEN_STEPS = frozenset({"show_initial_frame", "apply_initial_layout"})

SeriesBuilder = Callable[..., Path]

STARTUP_TRACE_FIXTURES: dict[str, tuple[SeriesBuilder, dict[str, Any]]] = {
    "ct_head": (build_synthetic_head_ct_series, {"num_slices": SYNTHETIC_VOLUME_MIN_SLICES}),
    "ct_chest": (build_synthetic_chest_ct_series, {"num_slices": SYNTHETIC_VOLUME_MIN_SLICES}),
    "ct_abdomen": (build_synthetic_abdomen_ct_series, {"num_slices": SYNTHETIC_VOLUME_MIN_SLICES}),
    "ct_small": (build_synthetic_ct_small_series, {"num_slices": SYNTHETIC_VOLUME_MIN_SLICES}),
    "ct_wide": (build_synthetic_wide_ct_series, {"num_slices": SYNTHETIC_VOLUME_MIN_SLICES}),
    "ct_single": (build_synthetic_single_slice_ct_series, {}),
    "ct_scout": (build_synthetic_scout_ct_series, {}),
    "ct_sagittal": (build_synthetic_sagittal_ct_series, {"num_slices": SYNTHETIC_VOLUME_MIN_SLICES}),
    "ct_coronal": (build_synthetic_coronal_ct_series, {"num_slices": SYNTHETIC_VOLUME_MIN_SLICES}),
    "ct_oblique": (build_synthetic_oblique_ct_series, {"num_slices": SYNTHETIC_VOLUME_MIN_SLICES}),
    "ct_perfusion": (build_synthetic_ct_perfusion_map_series, {"num_slices": SYNTHETIC_VOLUME_MIN_SLICES}),
    "ct_bolus": (build_synthetic_bolus_monitor_series, {"num_slices": SYNTHETIC_VOLUME_MIN_SLICES}),
    "ct_fused_pet": (build_synthetic_fused_pet_ct_series, {"num_slices": SYNTHETIC_VOLUME_MIN_SLICES}),
    "ct_mpr": (build_synthetic_derived_coronal_mpr_series, {"num_slices": SYNTHETIC_VOLUME_MIN_SLICES}),
    "ct_mip": (build_synthetic_derived_mip_series, {"num_slices": SYNTHETIC_VOLUME_MIN_SLICES}),
    "mr_breast_adc": (build_synthetic_breast_adc_mr_series, {"num_slices": SYNTHETIC_VOLUME_MIN_SLICES}),
    "mr_breast_anatomical": (build_synthetic_breast_mr_anatomical_series, {"num_slices": SYNTHETIC_VOLUME_MIN_SLICES}),
    "mr_survey": (build_synthetic_survey_mr_series, {"num_slices": SYNTHETIC_VOLUME_MIN_SLICES}),
    "mr_haste_sag": (build_synthetic_haste_sag_series, {"num_slices": SYNTHETIC_VOLUME_MIN_SLICES}),
}

EXPECTED_MODALITIES: dict[str, str] = {
    "mr_breast_adc": "MR",
    "mr_breast_anatomical": "MR",
    "mr_survey": "MR",
}


@dataclass(frozen=True)
class TraceStep:
    step: str
    fields: dict[str, str]


def build_startup_trace_series(fixture_id: str, output_dir: Path) -> tuple[Path, str]:
    """Build a synthetic series dir and return (path, DICOM Modality)."""
    builder, kwargs = STARTUP_TRACE_FIXTURES[fixture_id]
    series_dir = builder(output_dir / fixture_id, **kwargs)
    modality = str(dcmread(next(series_dir.glob("*.dcm")), stop_before_pixels=True).Modality)
    return series_dir, modality


def parse_size(value: str) -> tuple[int, int]:
    width_text, height_text = value.split("x", 1)
    return int(width_text), int(height_text)


def parse_series_view_load_trace(caplog) -> list[TraceStep]:
    records: list[TraceStep] = []
    for record in caplog.records:
        if record.name != TRACE_LOGGER:
            continue
        message = record.getMessage()
        if not message.startswith(TRACE_PREFIX):
            continue
        body = message[len(TRACE_PREFIX) :]
        fields: dict[str, str] = {}
        step: str | None = None
        for token in body.split():
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            if key == "step":
                step = value
            else:
                fields[key] = value
        if step is not None:
            records.append(TraceStep(step=step, fields=fields))
    return records


def _match_startup_sequence(records: list[TraceStep]) -> list[TraceStep]:
    steps = [record.step for record in records]
    expected = list(STARTUP_STEPS)
    for index in range(len(steps) - len(expected) + 1):
        if steps[index : index + len(expected)] == expected:
            return records[index : index + len(expected)]
    pytest.fail(f"startup trace missing ordered steps {expected}; got {steps}")


def assert_startup_trace(
    records: list[TraceStep],
    *,
    native_size: tuple[int, int],
    expected_display_size: tuple[int, int],
    expect_preloaded: bool = True,
    expect_segmentation_reserved: bool | None = None,
) -> None:
    forbidden = [record.step for record in records if record.step in FORBIDDEN_STEPS]
    assert not forbidden, f"obsolete startup steps in trace: {forbidden}"

    offset = 0
    if expect_preloaded:
        assert records, "expected preloaded trace step"
        assert records[0].step == "preloaded", records[0].step
        assert records[0].fields["frame"] == f"{native_size[0]}x{native_size[1]}"
        offset = 1

    matched = _match_startup_sequence(records[offset:])
    steps = [record.step for record in records[offset:]]
    assert steps.count("startup_paint") == 1, steps
    assert steps.count("startup_painted") == 1, steps

    native_text = f"{native_size[0]}x{native_size[1]}"
    display_text = f"{expected_display_size[0]}x{expected_display_size[1]}"
    native_match = expected_display_size == native_size

    finish_loading = matched[0]
    assert finish_loading.fields["frame"] == native_text

    startup_spec = next(record for record in matched if record.step == "startup_spec")
    assert startup_spec.fields["viewable"] == "0"
    assert startup_spec.fields["native"] == native_text
    assert startup_spec.fields["display"] == display_text
    assert "canvas" in startup_spec.fields
    if expect_segmentation_reserved is not None:
        assert startup_spec.fields.get("seg_reserved") == str(int(expect_segmentation_reserved))

    geometry_applied = next(record for record in matched if record.step == "geometry_applied")
    assert geometry_applied.fields["window"] == startup_spec.fields["window"]
    assert geometry_applied.fields["viewable"] == "0"

    for step_name in ("startup_paint", "startup_painted", "seg_chrome"):
        record = next(item for item in matched if item.step == step_name)
        assert record.fields["viewable"] == "0"
        if step_name in ("startup_paint", "startup_painted"):
            assert record.fields["display"] == display_text
        if step_name == "startup_painted":
            assert record.fields["frame_index"] == "0"

    deiconify = next(record for record in matched if record.step == "deiconify")
    assert deiconify.fields["viewable"] == "1"

    deiconify_index = matched.index(deiconify)
    for record in matched[:deiconify_index]:
        if "viewable" in record.fields:
            assert record.fields["viewable"] == "0", record.step

    startup_complete = next(record for record in matched if record.step == "startup_complete")
    assert startup_complete.fields["viewable"] == "1"
    assert startup_complete.fields["display"] == display_text
    assert startup_complete.fields["native_match"] == str(native_match)
