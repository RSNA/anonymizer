"""Unit tests for ct_eval confusion matrix helpers."""

from __future__ import annotations

from prototyping.ct_eval import (
    BODY_PART_NONE,
    BODY_PARTS,
    CONTRAST_LABELS,
    build_confusion_matrix,
    contrast_confusion_rows,
    body_part_confusion_rows,
)


def test_body_part_confusion_matrix() -> None:
    rows = [
        {
            "status": "ok",
            "body_part_gt": "Chest",
            "body_part_pred": "Chest",
            "iv_contrast_correct": True,
            "iv_contrast_pred": True,
        },
        {
            "status": "ok",
            "body_part_gt": "Chest",
            "body_part_pred": "Head",
            "iv_contrast_correct": True,
            "iv_contrast_pred": False,
        },
        {
            "status": "fail",
            "body_part_gt": "Head",
            "body_part_pred": "",
            "iv_contrast_correct": "",
            "iv_contrast_pred": "",
        },
    ]
    labels = BODY_PARTS + (BODY_PART_NONE,)
    y_true, y_pred = body_part_confusion_rows(rows)
    matrix = build_confusion_matrix(y_true, y_pred, labels, unknown_pred=BODY_PART_NONE)
    assert matrix[labels.index("Chest")][labels.index("Chest")] == 1
    assert matrix[labels.index("Chest")][labels.index("Head")] == 1


def test_contrast_confusion_matrix() -> None:
    rows = [
        {
            "status": "ok",
            "iv_contrast_gt": True,
            "iv_contrast_pred": True,
            "iv_contrast_correct": True,
        },
        {
            "status": "ok",
            "iv_contrast_gt": False,
            "iv_contrast_pred": True,
            "iv_contrast_correct": False,
        },
    ]
    y_true, y_pred = contrast_confusion_rows(rows)
    matrix = build_confusion_matrix(y_true, y_pred, CONTRAST_LABELS)
    assert matrix[CONTRAST_LABELS.index("WITH")][CONTRAST_LABELS.index("WITH")] == 1
    assert matrix[CONTRAST_LABELS.index("WITHOUT")][CONTRAST_LABELS.index("WITH")] == 1
