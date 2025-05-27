# test_create_projections_pytest.py

# Standard Library Imports
import logging  # For caplog level checking
import pickle
from pathlib import Path

# Third-Party Imports
import numpy as np
import pytest
from PIL import Image as PILImageModule
from pydicom import Dataset, multival
from pydicom.dataset import FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian

# Local Application/Library Specific Imports
from anonymizer.controller.create_projections import (
    Projection,  # Tested
    ProjectionImageSize,  # Tested
    ProjectionImageSizeConfig,  # Tested
    cache_projection,  # Tested
    clip_and_cast_to_int,  # Tested
    create_projection_from_single_frame,  # Tested
    get_wl_ww,  # Tested
    # The following are imported by create_projections but not directly used
    # in the tests shown below. If testing functions that use them,
    # they might need to be mocked or their effects considered.
    # PROJECTION_FILENAME,
    # VALID_COLOR_SPACES,
    # OCRText from anonymizer.controller.remove_pixel_phi is used by Projection
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
    def test_projection_cleanup(self, mocker, caplog: pytest.LogCaptureFixture):
        mock_img1 = mocker.MagicMock(spec=PILImageModule.Image)
        mock_img2 = mocker.MagicMock(spec=PILImageModule.Image)

        projection = Projection("pid", "study", "series", "desc", proj_images=[mock_img1, mock_img2])
        with caplog.at_level(logging.DEBUG):
            projection.cleanup()

        mock_img1.close.assert_called_once()
        mock_img2.close.assert_called_once()
        assert projection.proj_images is None
        assert projection.ocr is None
        assert "Cleaning up Projection for series: series" in caplog.text

    def test_projection_cleanup_with_close_error(self, mocker, caplog: pytest.LogCaptureFixture):
        mock_img1 = mocker.MagicMock(spec=PILImageModule.Image)
        mock_img1.close.side_effect = Exception("Close error")
        projection = Projection("pid", "study", "series", "desc", proj_images=[mock_img1])
        with caplog.at_level(logging.WARNING):
            projection.cleanup()
        assert "Error closing image: Close error" in caplog.text
        assert projection.proj_images is None

    def test_projection_context_manager(self, mocker):
        # Patching the method on the class itself
        mock_cleanup = mocker.patch("anonymizer.controller.create_projections.Projection.cleanup")
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

    def test_set_scaling_factor_if_needed_scaling_required(self, mocker, caplog):
        mock_set_factor = mocker.patch(
            "anonymizer.controller.create_projections.ProjectionImageSizeConfig.set_scaling_factor"
        )
        original_large_width = ProjectionImageSize.LARGE.value[0]
        screen_width = (original_large_width * 3) - 100

        with caplog.at_level(logging.INFO):
            ProjectionImageSizeConfig.set_scaling_factor_if_needed(screen_width)

        expected_factor = screen_width / (original_large_width * 3)
        mock_set_factor.assert_called_once_with(expected_factor)
        assert f"Scaling factor set to {expected_factor}" in caplog.text

    def test_set_scaling_factor_if_needed_no_scaling(self, mocker, caplog):
        mock_set_factor = mocker.patch(
            "anonymizer.controller.create_projections.ProjectionImageSizeConfig.set_scaling_factor"
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
    def test_normalize_uint8_call(self, mocker):
        mock_cv2_normalize = mocker.patch(
            "anonymizer.controller.create_projections.normalize"  # Assuming normalize is cv2.normalize
        )
        input_array = np.array([[0, 1000]], dtype=np.float32)
        mock_cv2_normalize.return_value = np.array([[0, 255]], dtype=np.float32)

        result = normalize_uint8(input_array)

        # NORM_MINMAX from cv2 is 32
        mock_cv2_normalize.assert_called_once_with(
            src=input_array,
            dst=mocker.ANY,
            alpha=0,
            beta=255,
            norm_type=32,  # cv2.NORM_MINMAX
            dtype=-1,
            mask=None,
        )
        assert result.dtype == np.uint8
        np.testing.assert_array_equal(result, np.array([[0, 255]], dtype=np.uint8))


class TestClipAndCastToInt:
    def test_clip_cast_uint16_no_clipping(self, caplog):
        float_arr = np.array([0.0, 100.5, 65535.0], dtype=np.float32)
        result = clip_and_cast_to_int(float_arr, np.uint16)
        expected = np.array([0, 100, 65535], dtype=np.uint16)

        assert result is not None, "Expected an array, not None"
        np.testing.assert_array_equal(result, expected)
        assert not any("Values were clipped" in record.message for record in caplog.records)

    def test_clip_cast_uint16_with_clipping(self, caplog):
        float_arr = np.array([-10.0, 300.7, 70000.0], dtype=np.float32)
        result = clip_and_cast_to_int(float_arr, np.uint16)
        expected = np.array([0, 300, 65535], dtype=np.uint16)

        assert result is not None, "Expected an array, not None"
        np.testing.assert_array_equal(result, expected)
        assert any(
            record.levelname == "WARNING"
            and "Values were clipped during conversion to <class 'numpy.uint16'>" in record.message
            and "Original range [-10.0..70000.0], Target range [0..65535]" in record.message
            for record in caplog.records
        )

    def test_non_float_input(self, caplog: pytest.LogCaptureFixture):
        int_arr = np.array([0, 100, 200], dtype=np.int32)
        result = clip_and_cast_to_int(int_arr, np.uint8)
        expected = np.array([0, 100, 200], dtype=np.uint8)

        assert result is not None, "Expected an array, not None"
        np.testing.assert_array_equal(result, expected)
        assert (f"Input array dtype is not float ({int_arr.dtype}), attempting conversion anyway.") in caplog.text

    def test_non_integer_target(self, caplog: pytest.LogCaptureFixture):
        float_arr = np.array([0.0, 1.0], dtype=np.float32)
        result = clip_and_cast_to_int(float_arr, np.float32)  # type: ignore[arg-type]
        assert result is None
        assert f"Target dtype {np.float32} is not an integer type." in caplog.text
        assert any(record.levelname == "ERROR" for record in caplog.records)

    def test_exception_handling(self, mocker, caplog: pytest.LogCaptureFixture):
        mocker.patch("anonymizer.controller.create_projections.np.iinfo", side_effect=Exception("Test iinfo error"))
        float_arr = np.array([0.0, 1.0], dtype=np.float32)
        result = clip_and_cast_to_int(float_arr, np.uint16)
        assert result is None  # This case correctly expects None
        assert "Test iinfo error" in caplog.text
        assert any(record.levelname == "ERROR" for record in caplog.records)


class TestCacheProjection:
    def test_cache_projection_success(self, mocker, caplog: pytest.LogCaptureFixture):
        mock_proj = mocker.MagicMock(spec=Projection)
        mock_path_obj = mocker.MagicMock(spec=Path)  # This is the Path object passed

        # Patch the built-in 'open' as it's seen by the 'cache_projection'
        # function within the 'anonymizer.controller.create_projections' module.
        # mocker.mock_open() creates a mock suitable for replacing 'open'.
        mock_open_func = mocker.mock_open()
        mocker.patch("anonymizer.controller.create_projections.open", mock_open_func)

        # Patch 'pickle.dump' in the context of the 'cache_projection' function
        # (it uses the globally imported pickle)
        mock_pickle_dump = mocker.patch("anonymizer.controller.create_projections.pickle.dump")

        with caplog.at_level(logging.WARNING):
            cache_projection(mock_proj, mock_path_obj)

        # Assert that the patched 'open' was called correctly with the Path object
        mock_open_func.assert_called_once_with(mock_path_obj, "wb")

        # Assert that pickle.dump was called with the projection and the file handle.
        # The file handle is what mock_open_func() (the result of its __enter__ method) returns.
        mock_pickle_dump.assert_called_once_with(mock_proj, mock_open_func())

        assert not caplog.records  # No warnings expected

    def test_cache_projection_pickle_error(self, mocker, caplog: pytest.LogCaptureFixture):
        mock_proj = mocker.MagicMock(spec=Projection)
        mock_path_obj = mocker.MagicMock(spec=Path)

        # Patch the built-in 'open'
        mock_open_func = mocker.mock_open()
        mocker.patch("anonymizer.controller.create_projections.open", mock_open_func)

        # Patch 'pickle.dump' and make it raise an error
        mocker.patch(
            "anonymizer.controller.create_projections.pickle.dump",
            side_effect=pickle.PicklingError("Test pickle error"),
        )

        with caplog.at_level(logging.WARNING):
            cache_projection(mock_proj, mock_path_obj)

        # 'open' should still be called
        mock_open_func.assert_called_once_with(mock_path_obj, "wb")
        assert "Error saving Projection cache file, error: Test pickle error" in caplog.text
        assert any(record.levelname == "WARNING" for record in caplog.records)


class TestGetWlWwPytest:
    def test_get_wl_ww_present_single_value(self):
        ds = create_basic_dataset()
        ds.WindowCenter = 100
        ds.WindowWidth = 200
        wl, ww = get_wl_ww(ds)
        assert wl == 100.0
        assert ww == 200.0

    def test_get_wl_ww_present_multivalue(self):
        ds = create_basic_dataset()
        ds.WindowCenter = multival.MultiValue(float, [50.5, 60])
        ds.WindowWidth = multival.MultiValue(float, [150.0, 180])
        wl, ww = get_wl_ww(ds)
        assert wl == 50.5
        assert ww == 150.0

    def test_get_wl_ww_width_less_than_1(self, caplog: pytest.LogCaptureFixture):
        ds = create_basic_dataset()
        ds.WindowCenter = 100
        ds.WindowWidth = 0.5
        with caplog.at_level(logging.WARNING):
            wl, ww = get_wl_ww(ds)
        assert wl == 100.0
        assert ww == 1.0
        assert "DICOM WindowWidth (0.5) is less than 1. Setting to 1." in caplog.text

    @pytest.mark.parametrize(
        "bits_allocated, expected_wl, expected_ww",
        [
            (8, 127.5, 255.0),
            (16, 32768.0, 65535.0),
            (12, 2048.0, 4096.0),
            (10, 512.0, 1024.0),
            (32, 2147483648.0, 4294967295.0),
        ],
    )
    def test_get_wl_ww_missing_defaults(self, bits_allocated, expected_wl, expected_ww):
        ds = create_basic_dataset()
        ds.BitsAllocated = bits_allocated
        if "WindowCenter" in ds:
            del ds.WindowCenter
        if "WindowWidth" in ds:
            del ds.WindowWidth

        wl, ww = get_wl_ww(ds)
        assert wl == expected_wl
        assert ww == expected_ww

    def test_get_wl_ww_missing_unsupported_bits(self):
        ds = create_basic_dataset()
        ds.BitsAllocated = 7
        with pytest.raises(ValueError, match="Unsupported BitsAllocated value: 7"):
            get_wl_ww(ds)

    def test_get_wl_ww_missing_bits_allocated(self):
        ds = create_basic_dataset()
        with pytest.raises(ValueError, match="Unsupported BitsAllocated value: None"):
            get_wl_ww(ds)


class TestCreateProjectionFromSingleFrame:
    def test_creation_logic(self, mocker):
        ds = create_basic_dataset()
        frame_data = np.random.randint(0, 1000, size=(50, 50), dtype=np.int16)

        # 1. Create a mock for what ProjectionImageSize.LARGE would be.
        #    This mock needs a '.value' attribute.
        mock_large_member_instance = mocker.MagicMock()
        mock_large_member_instance.value = (120, 120)  # The desired (width, height)

        # 2. Create a mock for the ProjectionImageSize enum class itself.
        mock_enum_class = mocker.MagicMock()

        # 3. Configure the mocked Enum class so that accessing its 'LARGE' attribute
        #    (as if it were ProjectionImageSize.LARGE)
        #    returns your mock_large_member_instance.
        #    We use type() to set this up as a class-level attribute on the mock.
        type(mock_enum_class).LARGE = mocker.PropertyMock(return_value=mock_large_member_instance)
        # You could also mock other members like SMALL, MEDIUM if they were used.
        # type(mock_enum_class).SMALL = mocker.PropertyMock(...)

        # 4. Patch the *actual* ProjectionImageSize class in the module under test
        #    to be replaced by your mock_enum_class.
        mocker.patch("anonymizer.controller.create_projections.ProjectionImageSize", new=mock_enum_class)

        # --- Rest of your mocks for cv2 and PIL functions ---
        # Ensure patch paths are correct, targeting where they are used within
        # 'anonymizer.controller.create_projections'.
        mock_clahe_apply = mocker.Mock(return_value=np.zeros((50, 50), np.uint8))
        mock_create_clahe = mocker.patch(
            "anonymizer.controller.create_projections.createCLAHE",
            return_value=mocker.Mock(apply=mock_clahe_apply),
        )
        mock_gaussian_blur = mocker.patch(
            "anonymizer.controller.create_projections.GaussianBlur",
            return_value=np.zeros((50, 50), np.uint8),
        )
        mock_canny = mocker.patch(
            "anonymizer.controller.create_projections.Canny",
            return_value=np.zeros((50, 50), np.uint8),
        )
        mock_get_struct_element = mocker.patch(
            "anonymizer.controller.create_projections.getStructuringElement", return_value=np.array([])
        )
        mock_dilate = mocker.patch(
            "anonymizer.controller.create_projections.dilate", return_value=np.zeros((50, 50), np.uint8)
        )

        mock_pil_image_instance = mocker.MagicMock()
        # Assuming 'Image' is imported as 'from PIL import Image'
        # in 'anonymizer.controller.create_projections'
        mock_pil_fromarray = mocker.patch("anonymizer.controller.create_projections.Image.fromarray")
        mock_pil_fromarray.return_value.convert.return_value.resize.return_value = mock_pil_image_instance

        # --- Call the function under test ---
        projection = create_projection_from_single_frame(ds, frame_data)

        # --- Assertions ---
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
        mock_gaussian_blur.assert_called_once()  # Check arguments if necessary
        mock_canny.assert_called_once()  # Check arguments if necessary
        mock_get_struct_element.assert_called_once()  # Check arguments if necessary
        mock_dilate.assert_called_once()  # Check arguments if necessary

        assert mock_pil_fromarray.call_count == 3
        assert mock_pil_fromarray.return_value.convert.call_count == 3
        mock_pil_fromarray.return_value.convert.assert_called_with("RGB")

        assert mock_pil_fromarray.return_value.convert.return_value.resize.call_count == 3
        # Verify resize call uses the mocked value
        resize_call_args = mock_pil_fromarray.return_value.convert.return_value.resize.call_args_list[0]
        # The first argument to resize should be the tuple (width, height)
        assert resize_call_args.args[0] == (120, 120)
        assert resize_call_args.args[1] == PILImageModule.Resampling.NEAREST
