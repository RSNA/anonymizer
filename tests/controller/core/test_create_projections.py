# test_create_projections_pytest.py

# Standard Library Imports
import logging  # For caplog level checking
import pickle
from pathlib import Path
from unittest.mock import ANY, MagicMock, PropertyMock, mock_open, patch

# Third-Party Imports
import numpy as np
import pytest
from PIL import Image as PILImageModule
from pydicom import Dataset
from pydicom.dataset import FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian

# Local Application/Library Specific Imports
from anonymizer.controller.create_projections import (
    Projection,  # Tested
    ProjectionImageSize,  # Tested
    ProjectionImageSizeConfig,  # Tested
    cache_projection,  # Tested
    create_projection_from_single_frame,  # Tested
    normalize_uint8,  # Tested
)


# Helper to create a basic DICOM dataset for tests
def create_basic_dataset() -> Dataset:
    ds = Dataset()
    ds.PatientID = "TestPatientID"
    ds.StudyInstanceUID = "1.2.3"
    ds.SeriesInstanceUID = "1.2.3.4"
    ds.SeriesDescription = "Test Series"
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.is_implicit_VR = False
    ds.is_little_endian = True
    return ds


class TestProjectionDataclassPytest:
    def test_projection_cleanup(self, caplog: pytest.LogCaptureFixture):
        mock_img1 = MagicMock(spec=PILImageModule.Image)
        mock_img2 = MagicMock(spec=PILImageModule.Image)

        projection = Projection("pid", "study", "series", "desc", proj_images=[mock_img1, mock_img2])
        with caplog.at_level(logging.DEBUG):
            projection.cleanup()

        mock_img1.close.assert_called_once()
        mock_img2.close.assert_called_once()
        assert projection.proj_images is None
        assert projection.ocr is None
        assert "Cleaning up Projection for series: series" in caplog.text

    def test_projection_cleanup_with_close_error(self, caplog: pytest.LogCaptureFixture):
        mock_img1 = MagicMock(spec=PILImageModule.Image)
        mock_img1.close.side_effect = Exception("Close error")
        projection = Projection("pid", "study", "series", "desc", proj_images=[mock_img1])
        with caplog.at_level(logging.WARNING):
            projection.cleanup()
        assert "Error closing image: Close error" in caplog.text
        assert projection.proj_images is None

    def test_projection_context_manager(self, monkeypatch):
        mock_cleanup = MagicMock()
        monkeypatch.setattr("anonymizer.controller.create_projections.Projection.cleanup", mock_cleanup)
        projection_instance = Projection("pid", "study", "series", "desc")
        with projection_instance as p:
            assert p is projection_instance
        mock_cleanup.assert_called_once()


@pytest.fixture
def reset_scaling_factor_fixture():
    # Ensure the config is imported from the correct new path if it's not already
    from anonymizer.controller.create_projections import ProjectionImageSizeConfig

    original_factor = ProjectionImageSizeConfig._scaling_factor
    ProjectionImageSizeConfig._scaling_factor = 1.0  # Setup
    yield  # Test runs here
    ProjectionImageSizeConfig._scaling_factor = original_factor  # Teardown


@pytest.mark.usefixtures("reset_scaling_factor_fixture")
class TestProjectionImageSizeConfigPytest:
    def test_set_get_scaling_factor(self):
        ProjectionImageSizeConfig.set_scaling_factor(0.5)
        assert ProjectionImageSizeConfig.get_scaling_factor() == 0.5

    def test_set_scaling_factor_invalid(self):
        with pytest.raises(ValueError, match="Scaling factor must be greater than zero."):
            ProjectionImageSizeConfig.set_scaling_factor(0)
        with pytest.raises(ValueError, match="Scaling factor must be greater than zero."):
            ProjectionImageSizeConfig.set_scaling_factor(-1.0)

    def test_set_scaling_factor_if_needed_scaling_required(self, monkeypatch, caplog):
        mock_set_factor = MagicMock()
        monkeypatch.setattr(
            "anonymizer.controller.create_projections.ProjectionImageSizeConfig.set_scaling_factor",
            mock_set_factor,
        )
        original_large_width = ProjectionImageSize.LARGE.value[0]
        screen_width = (original_large_width * 3) - 100

        with caplog.at_level(logging.INFO):
            ProjectionImageSizeConfig.set_scaling_factor_if_needed(screen_width)

        expected_factor = screen_width / (original_large_width * 3)
        mock_set_factor.assert_called_once_with(expected_factor)
        assert f"Scaling factor set to {expected_factor}" in caplog.text

    def test_set_scaling_factor_if_needed_no_scaling(self, monkeypatch, caplog):
        mock_set_factor = MagicMock()
        monkeypatch.setattr(
            "anonymizer.controller.create_projections.ProjectionImageSizeConfig.set_scaling_factor",
            mock_set_factor,
        )
        original_large_width = ProjectionImageSize.LARGE.value[0]
        screen_width = original_large_width * 3

        with caplog.at_level(logging.INFO):
            ProjectionImageSizeConfig.set_scaling_factor_if_needed(screen_width)

        mock_set_factor.assert_called_once_with(1.0)
        assert "Scaling factor reset to 1.0" in caplog.text


@pytest.mark.usefixtures("reset_scaling_factor_fixture")
class TestProjectionImageSizeEnum:
    def test_width_height_no_scaling(self):
        assert ProjectionImageSize.SMALL.width() == 200
        assert ProjectionImageSize.SMALL.height() == 200
        assert ProjectionImageSize.LARGE.width() == 800
        assert ProjectionImageSize.LARGE.height() == 800

    def test_width_height_with_scaling(self):
        ProjectionImageSizeConfig.set_scaling_factor(0.5)
        assert ProjectionImageSize.SMALL.width() == 100
        assert ProjectionImageSize.SMALL.height() == 100
        assert ProjectionImageSize.LARGE.width() == 400
        assert ProjectionImageSize.LARGE.height() == 400


class TestNormalizeUint8:
    def test_normalize_uint8_call(self):
        input_array = np.array([[0, 1000]], dtype=np.float32)
        with patch("anonymizer.controller.create_projections.normalize") as mock_cv2_normalize:
            mock_cv2_normalize.return_value = np.array([[0, 255]], dtype=np.float32)

            result = normalize_uint8(input_array)

            # NORM_MINMAX from cv2 is 32
            mock_cv2_normalize.assert_called_once_with(
                src=input_array,
                dst=ANY,
                alpha=0,
                beta=255,
                norm_type=32,  # cv2.NORM_MINMAX
                dtype=-1,
                mask=None,
            )
        assert result.dtype == np.uint8
        np.testing.assert_array_equal(result, np.array([[0, 255]], dtype=np.uint8))


class TestCacheProjection:
    def test_cache_projection_success(self, caplog: pytest.LogCaptureFixture):
        mock_proj = MagicMock(spec=Projection)
        mock_path_obj = MagicMock(spec=Path)
        mock_open_func = mock_open()
        with (
            patch("anonymizer.controller.create_projections.open", mock_open_func),
            patch("anonymizer.controller.create_projections.pickle.dump") as mock_pickle_dump,
        ):
            with caplog.at_level(logging.WARNING):
                cache_projection(mock_proj, mock_path_obj)

        mock_open_func.assert_called_once_with(mock_path_obj, "wb")
        mock_pickle_dump.assert_called_once_with(mock_proj, mock_open_func())
        assert not caplog.records  # No warnings expected

    def test_cache_projection_pickle_error(self, caplog: pytest.LogCaptureFixture):
        mock_proj = MagicMock(spec=Projection)
        mock_path_obj = MagicMock(spec=Path)
        mock_open_func = mock_open()
        with (
            patch("anonymizer.controller.create_projections.open", mock_open_func),
            patch(
                "anonymizer.controller.create_projections.pickle.dump",
                side_effect=pickle.PicklingError("Test pickle error"),
            ),
        ):
            with caplog.at_level(logging.WARNING):
                cache_projection(mock_proj, mock_path_obj)

        mock_open_func.assert_called_once_with(mock_path_obj, "wb")
        assert "Error saving Projection cache file, error: Test pickle error" in caplog.text
        assert any(record.levelname == "WARNING" for record in caplog.records)


class TestCreateProjectionFromSingleFrame:
    def test_creation_logic(self):
        ds = create_basic_dataset()
        frame_data = np.random.randint(0, 1000, size=(50, 50), dtype=np.int16)

        mock_large_member_instance = MagicMock()
        mock_large_member_instance.value = (120, 120)
        mock_enum_class = MagicMock()
        type(mock_enum_class).LARGE = PropertyMock(return_value=mock_large_member_instance)

        mock_clahe_apply = MagicMock(return_value=np.zeros((50, 50), np.uint8))
        mock_pil_image_instance = MagicMock()

        with (
            patch("anonymizer.controller.create_projections.ProjectionImageSize", new=mock_enum_class),
            patch(
                "anonymizer.controller.create_projections.createCLAHE",
                return_value=MagicMock(apply=mock_clahe_apply),
            ) as mock_create_clahe,
            patch(
                "anonymizer.controller.create_projections.GaussianBlur",
                return_value=np.zeros((50, 50), np.uint8),
            ) as mock_gaussian_blur,
            patch(
                "anonymizer.controller.create_projections.Canny",
                return_value=np.zeros((50, 50), np.uint8),
            ) as mock_canny,
            patch(
                "anonymizer.controller.create_projections.getStructuringElement",
                return_value=np.array([]),
            ) as mock_get_struct_element,
            patch(
                "anonymizer.controller.create_projections.dilate",
                return_value=np.zeros((50, 50), np.uint8),
            ) as mock_dilate,
            patch("anonymizer.controller.create_projections.Image.fromarray") as mock_pil_fromarray,
        ):
            mock_pil_fromarray.return_value.convert.return_value.resize.return_value = mock_pil_image_instance
            projection = create_projection_from_single_frame(ds, frame_data)

        assert projection.patient_id == ds.PatientID
        assert projection.study_uid == ds.StudyInstanceUID
        assert projection.series_uid == ds.SeriesInstanceUID
        assert projection.series_description == ds.SeriesDescription
        assert projection.ocr is None
        assert projection.proj_images is not None
        assert len(projection.proj_images) == 3
        for img in projection.proj_images:
            assert img is mock_pil_image_instance

        mock_create_clahe.assert_called_once_with(clipLimit=2.0, tileGridSize=(8, 8))
        mock_clahe_apply.assert_called_once()
        clahe_src = mock_clahe_apply.call_args.args[0]
        assert clahe_src.ndim == 2
        assert clahe_src.dtype == np.uint8
        mock_gaussian_blur.assert_called_once()
        mock_canny.assert_called_once()
        mock_get_struct_element.assert_called_once()
        mock_dilate.assert_called_once()

        assert mock_pil_fromarray.call_count == 3
        assert mock_pil_fromarray.return_value.convert.call_count == 3
        mock_pil_fromarray.return_value.convert.assert_called_with("RGB")

        assert mock_pil_fromarray.return_value.convert.return_value.resize.call_count == 3
        resize_call_args = mock_pil_fromarray.return_value.convert.return_value.resize.call_args_list[0]
        assert resize_call_args.args[0] == (120, 120)
        assert resize_call_args.args[1] == PILImageModule.Resampling.NEAREST

    def test_rgb_ultrasound_frame_runs_clahe(self):
        """Color US frames are HxWx3; CLAHE requires single-channel uint8."""
        ds = create_basic_dataset()
        frame = np.random.randint(0, 255, size=(40, 50, 3), dtype=np.uint8)

        projection = create_projection_from_single_frame(ds, frame)

        assert projection.proj_images is not None
        assert len(projection.proj_images) == 3
        for img in projection.proj_images:
            assert img.mode == "RGB"
            assert img.size == ProjectionImageSize.LARGE.value
