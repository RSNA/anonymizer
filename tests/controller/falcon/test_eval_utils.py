"""Unit tests for FALCON eval_utils (model-input PNG export and thumbnails)."""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from anonymizer.controller.falcon.eval_utils import (
    BODY_PART_MODEL_INPUT_Z_INDEX,
    contrast_model_input_z_index,
    save_body_part_model_input_png,
    save_contrast_model_input_png,
    save_model_input_slice_png,
)
from anonymizer.controller.falcon.predict import extract_body_part_model_input_slice, extract_contrast_model_input_slice
from anonymizer.controller.falcon.preprocessing.preprocess_series import preprocess_series
from tests.controller.tseg.support.synthetic_ct import write_synthetic_phantom_assets
from tests.controller.paths import CONTROLLER_TEST_DCM_FILES_DIR

SYNTHETIC_DIRS = {
    "HeadNeck": CONTROLLER_TEST_DCM_FILES_DIR / "synthetic_CT_head",
    "Chest": CONTROLLER_TEST_DCM_FILES_DIR / "synthetic_CT_chest",
    "Abdomen": CONTROLLER_TEST_DCM_FILES_DIR / "synthetic_CT_abdomen",
}


@pytest.fixture(scope="session", autouse=True)
def ensure_synthetic_assets():
    head_neck_dir = SYNTHETIC_DIRS["HeadNeck"]
    needs_generation = not head_neck_dir.exists() or not list(head_neck_dir.glob("*.dcm"))
    if needs_generation:
        write_synthetic_phantom_assets()


def test_save_model_input_slice_png_with_title(tmp_path: Path) -> None:
    slice_2d = np.full((150, 150), 0.5, dtype=np.float32)
    output_png = tmp_path / "annotated.png"
    save_model_input_slice_png(slice_2d, output_png, title="GT: WITH->WITHOUT\n80%")

    with Image.open(output_png) as image:
        assert image.mode == "RGB"
        assert image.getpixel((5, 5)) == (0, 0, 0)


@pytest.mark.parametrize(
    ("phantom_key", "body_part", "z_index"),
    (
        ("HeadNeck", "HeadNeck", contrast_model_input_z_index("HeadNeck")),
        ("Chest", "Chest", contrast_model_input_z_index("Chest")),
        ("Abdomen", "Abdomen", contrast_model_input_z_index("Abdomen")),
    ),
)
def test_save_contrast_model_input_png_synthetic(
    phantom_key: str, body_part: str, z_index: int, tmp_path: Path
) -> None:
    series_dir = SYNTHETIC_DIRS[phantom_key]
    image_np = preprocess_series(series_dir)
    assert image_np.shape[0] > z_index

    output_png = tmp_path / phantom_key / "contrast_model_input.png"
    save_contrast_model_input_png(image_np, body_part, output_png)

    assert output_png.is_file()
    slice_2d = extract_contrast_model_input_slice(image_np, body_part)
    reloaded = np.asarray(Image.open(output_png), dtype=np.float32) / 255.0
    np.testing.assert_allclose(reloaded, slice_2d, atol=1.0 / 255.0)


@pytest.mark.parametrize("phantom_key", ("HeadNeck", "Chest", "Abdomen"))
def test_save_body_part_model_input_png_synthetic(phantom_key: str, tmp_path: Path) -> None:
    series_dir = SYNTHETIC_DIRS[phantom_key]
    image_np = preprocess_series(series_dir)
    assert image_np.shape[0] > BODY_PART_MODEL_INPUT_Z_INDEX

    output_png = tmp_path / phantom_key / "body_part_model_input.png"
    save_body_part_model_input_png(image_np, output_png)

    assert output_png.is_file()
    with Image.open(output_png) as image:
        assert image.mode == "L"
        assert image.size == (image_np.shape[2], image_np.shape[1])

    titled_png = tmp_path / phantom_key / "body_part_titled.png"
    save_body_part_model_input_png(
        image_np,
        titled_png,
        title="GT: HEADNECK->CHEST\n80%",
    )
    with Image.open(titled_png) as image:
        assert image.mode == "RGB"

    slice_2d = extract_body_part_model_input_slice(image_np)
    reloaded = np.asarray(Image.open(output_png), dtype=np.float32) / 255.0
    np.testing.assert_allclose(reloaded, slice_2d, atol=1.0 / 255.0)
