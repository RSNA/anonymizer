"""Tests for shared series overlay DTOs and segmentation rendering."""

from __future__ import annotations

from anonymizer.controller.series_overlay import (
    COLORED_SEGMENTATION_OUTLINE_THICKNESS,
    COLORED_SEGMENTATION_OUTLINE_UNDERLAY_THICKNESS,
    LayerType,
    OCRText,
    OverlayData,
    PolygonPoint,
    Segmentation,
    UserRectangle,
    render_segmentations_overlay,
)


def test_segmentation_optional_fields_default_none() -> None:
    seg = Segmentation(points=[PolygonPoint(x=1, y=2)])
    assert seg.color_bgr is None
    assert seg.structure_name is None


def test_overlay_data_defaults_empty() -> None:
    data = OverlayData()
    assert data.ocr_texts == []
    assert data.user_rects == []
    assert data.segmentations == []


def test_ocr_text_box_helpers() -> None:
    text = OCRText(text="A", top_left=(1, 2), bottom_right=(11, 12), prob=0.5)
    assert text.get_bounding_box() == (1, 2, 11, 12)
    assert text.box_area() == 100


def test_user_rectangle_bounding_box() -> None:
    rect = UserRectangle(top_left=(0, 0), bottom_right=(5, 7))
    assert rect.get_bounding_box() == (0, 0, 5, 7)


def test_layer_type_members() -> None:
    assert {LayerType.TEXT, LayerType.USER_RECT, LayerType.SEGMENTATIONS} == set(LayerType)


def _square(x0: int, y0: int, x1: int, y1: int) -> list[PolygonPoint]:
    return [
        PolygonPoint(x=x0, y=y0),
        PolygonPoint(x=x1, y=y0),
        PolygonPoint(x=x1, y=y1),
        PolygonPoint(x=x0, y=y1),
    ]


def test_unset_color_fills_solid_default() -> None:
    color = (0, 255, 0)
    overlay = render_segmentations_overlay(
        40,
        40,
        [Segmentation(points=_square(10, 10, 30, 30))],
        default_color_bgr=color,
    )
    center = overlay[20, 20]
    assert tuple(center) == color


def test_colored_segmentation_outline_only_no_fill() -> None:
    color = (0, 0, 255)
    overlay = render_segmentations_overlay(
        50,
        50,
        [Segmentation(points=_square(10, 10, 40, 40), color_bgr=color, structure_name="heart")],
        default_color_bgr=(255, 255, 255),
    )
    # Interior stays empty (no fill).
    assert tuple(overlay[25, 25]) == (0, 0, 0)
    # Edge carries solid outline color (opaque stroke, not CT-blended).
    edge = overlay[10, 25]
    assert tuple(edge) == color
    assert COLORED_SEGMENTATION_OUTLINE_THICKNESS == 2
    assert COLORED_SEGMENTATION_OUTLINE_UNDERLAY_THICKNESS > COLORED_SEGMENTATION_OUTLINE_THICKNESS
    assert tuple(overlay[2, 2]) == (0, 0, 0)


def test_colored_outline_is_opaque_solid_not_additive() -> None:
    """Outline pixels are exact structure color (no AA muddying / no transparency)."""
    color = (14, 127, 255)  # liver BGR
    overlay = render_segmentations_overlay(
        40,
        40,
        [Segmentation(points=_square(8, 8, 32, 32), color_bgr=color, structure_name="liver")],
        default_color_bgr=(0, 0, 0),
    )
    edge = overlay[8, 20]
    assert tuple(edge) == color


def test_colored_outline_draws_black_understroke() -> None:
    from anonymizer.controller.series_overlay import COLORED_SEGMENTATION_OUTLINE_UNDERLAY_BGR

    color = (0, 0, 255)
    overlay = render_segmentations_overlay(
        50,
        50,
        [Segmentation(points=_square(15, 15, 35, 35), color_bgr=color, structure_name="heart")],
        default_color_bgr=(255, 255, 255),
    )
    assert tuple(overlay[0, 0]) == (0, 0, 0)
    assert tuple(overlay[15, 25]) == color
    # Outer fringe of the thicker understroke (outside the color stroke).
    under = overlay[15 - COLORED_SEGMENTATION_OUTLINE_UNDERLAY_THICKNESS // 2, 25]
    assert tuple(under) == COLORED_SEGMENTATION_OUTLINE_UNDERLAY_BGR


def test_primary_head_colors_are_distinct() -> None:
    from anonymizer.controller.ai.anatomy_overlay import color_bgr_for_structure

    colors = {
        color_bgr_for_structure("brain"),
        color_bgr_for_structure("skull"),
        color_bgr_for_structure("spine"),
        color_bgr_for_structure("spinal_cord"),
    }
    assert len(colors) == 4
