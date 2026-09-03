"""Parse and assert ProjectionView startup traces from caplog."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

TRACE_LOGGER = "anonymizer.view.series.projection"
TRACE_PREFIX = "ProjectionView startup: "

STARTUP_STEPS = (
    "widgets_done",
    "populate_start",
    "populate_done",
    "deiconify",
)


@dataclass(frozen=True)
class TraceStep:
    step: str
    fields: dict[str, str]


def parse_projection_view_startup_trace(caplog) -> list[TraceStep]:
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


def assert_projection_startup_trace(records: list[TraceStep]) -> None:
    steps = [record.step for record in records]
    for index in range(len(steps) - len(STARTUP_STEPS) + 1):
        if steps[index : index + len(STARTUP_STEPS)] == list(STARTUP_STEPS):
            matched = records[index : index + len(STARTUP_STEPS)]
            break
    else:
        pytest.fail(f"projection startup trace missing ordered steps {STARTUP_STEPS}; got {steps}")

    for record in matched[:-1]:
        if "viewable" in record.fields:
            assert record.fields["viewable"] == "0", record.step

    deiconify = matched[-1]
    assert deiconify.step == "deiconify"
    assert deiconify.fields["viewable"] == "1"
