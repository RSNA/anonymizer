from typing import List
from pynetdicom.ae import ApplicationEntity as AE
from pynetdicom.presentation import PresentationContext, build_context
from pynetdicom._globals import ALL_TRANSFER_SYNTAXES, DEFAULT_TRANSFER_SYNTAXES

_Verification_Class = "1.2.840.10008.1.1"
_STUDY_ROOT_QR_CLASSES = [
    "1.2.840.10008.5.1.4.1.2.2.1",  # Find
    "1.2.840.10008.5.1.4.1.2.2.2",  # Move
    "1.2.840.10008.5.1.4.1.2.2.3",  # Get
]

_TRANSFER_SYNTAXES = DEFAULT_TRANSFER_SYNTAXES

# TODO: provide UX for these classes and supported transfer syntaxes
_RADIOLOGY_STORAGE_CLASSES = {
    "Computed Radiography Image Storage": "1.2.840.10008.5.1.4.1.1.1",
    "Computed Tomography Image Storage": "1.2.840.10008.5.1.4.1.1.2",
    # "Enhanced CT Image Storage": "1.2.840.10008.5.1.4.1.1.2.1",
    "Digital X-Ray Image Storage - For Presentation": "1.2.840.10008.5.1.4.1.1.1.1",
    "Digital X-Ray Image Storage - For Processing": "1.2.840.10008.5.1.4.1.1.1.1.1",
    # "Digital Mammography X-Ray Image Storage For Presentation": "1.2.840.10008.5.1.4.1.1.1.2",
    # "Digital Mammography X-Ray Image Storage For Processing": "1.2.840.10008.5.1.4.1.1.1.2.1",
    # "Digital Intra Oral X-Ray Image Storage For Presentation": "1.2.840.10008.5.1.4.1.1.1.3",
    # "Digital Intra Oral X-Ray Image Storage For Processing": "1.2.840.10008.5.1.4.1.1.1.3.1",
    "Magnetic Resonance Image Storage": "1.2.840.10008.5.1.4.1.1.4",
    # "Enhanced MR Image Storage": "1.2.840.10008.5.1.4.1.1.4.1",
    # "Positron Emission Tomography Image Storage": "1.2.840.10008.5.1.4.1.1.128",
    # "Enhanced PET Image Storage": "1.2.840.10008.5.1.4.1.1.130",
    # "Ultrasound Image Storage": "1.2.840.10008.5.1.4.1.1.6.1",
    # "Mammography CAD SR Storage": "1.2.840.10008.5.1.4.1.1.88.50",
    # "BreastTomosynthesisImageStorage": "1.2.840.10008.5.1.4.1.1.13.1.3",
}

# TODO: provide UX for network timeout
_network_timeout = 3  # seconds


# Set *all* AE timeouts to the global network timeout:
def set_network_timeout(ae: AE) -> None:
    ae.acse_timeout = _network_timeout
    ae.dimse_timeout = _network_timeout
    ae.network_timeout = _network_timeout
    ae.connection_timeout = _network_timeout
    return


def get_network_timeout() -> int:
    return _network_timeout


# FOR SCP AE: Set allowed storage and verification contexts and corresponding transfer syntaxes
def set_verification_context(ae: AE):
    ae.add_supported_context(_Verification_Class, _TRANSFER_SYNTAXES)
    return


def set_radiology_storage_contexts(ae: AE) -> None:
    for uid in sorted(_RADIOLOGY_STORAGE_CLASSES.values()):
        ae.add_supported_context(uid, _TRANSFER_SYNTAXES)
    return


def set_study_root_qr_contexts(ae: AE) -> None:
    for uid in sorted(_STUDY_ROOT_QR_CLASSES):
        ae.add_supported_context(uid, _TRANSFER_SYNTAXES)
    return


# FOR SCU Association:
def get_verification_context() -> PresentationContext:
    return build_context(
        _Verification_Class, _TRANSFER_SYNTAXES
    )  # do not include compressed transfer syntaxes


def get_radiology_storage_contexts() -> List[PresentationContext]:
    return [
        build_context(abstract_syntax, _TRANSFER_SYNTAXES)
        for abstract_syntax in _RADIOLOGY_STORAGE_CLASSES.values()
    ]


def get_study_root_qr_contexts() -> List[PresentationContext]:
    return [
        build_context(abstract_syntax, _TRANSFER_SYNTAXES)
        for abstract_syntax in _STUDY_ROOT_QR_CLASSES
    ]
