"""Date-remap scoring covers calibration dates that do not end with 'Date'."""

from prototyping.pseudo_phi_deid.score import _is_date_remap_leaf


def test_calibration_dates_are_date_remap_leaves() -> None:
    assert _is_date_remap_leaf("DateOfLastCalibration")
    assert _is_date_remap_leaf("DateOfLastDetectorCalibration")
    assert _is_date_remap_leaf("DateTimeOfLastCalibration")
    assert _is_date_remap_leaf("AcquisitionDateTime")
    assert _is_date_remap_leaf("StudyDate")
    assert not _is_date_remap_leaf("PatientSex")
