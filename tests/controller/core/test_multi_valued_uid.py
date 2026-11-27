from pydicom import dcmread
from pydicom.data import get_testdata_file

from anonymizer.controller.project import ProjectController
from tests.controller.dicom.support.test_files import ct_small_filename
from tests.controller.dicom.support.test_nodes import LocalSCU


def test_multi_valued_uid_maps_each_value(controller: ProjectController) -> None:
    """@uid on a VM 1-n UI element (Irradiation Event UID) remaps every value."""
    ds = dcmread(get_testdata_file(ct_small_filename))
    ds.PatientID = "MULTI-UID-PT"
    ds.IrradiationEventUID = ["1.2.3.4.1", "1.2.3.4.2"]

    assert controller.anonymizer.anonymize(LocalSCU, ds) is None

    model = controller.anonymizer.model
    assert list(ds.IrradiationEventUID) == [
        model.get_anon_uid("1.2.3.4.1"),
        model.get_anon_uid("1.2.3.4.2"),
    ]
