from typing import Dict, Tuple

from anonymizer.utils.translate import _

# List of supported Modalities
# Modality Code => Description, Set of Related SOP Storage Class UIDs

# see: https://dicom.nema.org/medical/dicom/current/output/chtml/part16/sect_CID_29.html


# Description dynamically updated due to language dependency
def get_modalities() -> Dict[str, Tuple[str, list[str]]]:

    return {
        "CR": (_("Computed Radiography"), ["1.2.840.10008.5.1.4.1.1.1"]),
        "DX": (
            _("Digital X-Ray"),
            ["1.2.840.10008.5.1.4.1.1.1.1", "1.2.840.10008.5.1.4.1.1.1.1.1"],
        ),
        "IO": (
            _("Intra-oral Radiography"),
            ["1.2.840.10008.5.1.4.1.1.1.3", "1.2.840.10008.5.1.4.1.1.1.3.1"],
        ),
        "MG": (
            _("Mammography"),
            [
                "1.2.840.10008.5.1.4.1.1.1.2",
                "1.2.840.10008.5.1.4.1.1.1.2.1",
                "1.2.840.10008.5.1.4.1.1.13.1.3",
                "1.2.840.10008.5.1.4.1.1.13.1.4",
                "1.2.840.10008.5.1.4.1.1.13.1.5",
            ],
        ),
        "CT": (
            _("Computer Tomography"),
            [
                "1.2.840.10008.5.1.4.1.1.2",
                "1.2.840.10008.5.1.4.1.1.2.1",
                "1.2.840.10008.5.1.4.1.1.2.2",
            ],
        ),
        "MR": (
            _("Magnetic Resonance"),
            ["1.2.840.10008.5.1.4.1.1.4", "1.2.840.10008.5.1.4.1.1.4.1"],
        ),
        "US": (
            _("Ultrasound"),
            ["1.2.840.10008.5.1.4.1.1.6.1", "1.2.840.10008.5.1.4.1.1.6.2", "1.2.840.10008.5.1.4.1.1.3.1"],
        ),
        "PT": (
            _("Positron Emission Tomography"),
            [
                "1.2.840.10008.5.1.4.1.1.128",
                "1.2.840.10008.5.1.4.1.1.128.1",
                "1.2.840.10008.5.1.4.1.1.130",
            ],
        ),
        "NM": (_("Nuclear Medicine"), ["1.2.840.10008.5.1.4.1.1.20"]),
        "SC": (_("Secondary Capture"), ["1.2.840.10008.5.1.4.1.1.7"]),
        "SR": (
            _("Structured Report"),
            [
                "1.2.840.10008.5.1.4.1.1.88.11",
                "1.2.840.10008.5.1.4.1.1.88.22",
                "1.2.840.10008.5.1.4.1.1.88.33",
                "1.2.840.10008.5.1.4.1.1.88.34",
                "1.2.840.10008.5.1.4.1.1.88.35",
            ],
        ),
        "PR": (
            _("Presentation State"),
            [
                "1.2.840.10008.5.1.4.1.1.11.1",
                "1.2.840.10008.5.1.4.1.1.11.2",
                "1.2.840.10008.5.1.4.1.1.11.3",
                "1.2.840.10008.5.1.4.1.1.11.4",
                "1.2.840.10008.5.1.4.1.1.11.5",
                "1.2.840.10008.5.1.4.1.1.11.6",
                "1.2.840.10008.5.1.4.1.1.11.7",
                "1.2.840.10008.5.1.4.1.1.11.8",
                "1.2.840.10008.5.1.4.1.1.11.9",
                "1.2.840.10008.5.1.4.1.1.11.10",
                "1.2.840.10008.5.1.4.1.1.11.11",
            ],
        ),
        "PDF": (_("Encapsulated PDF"), ["1.2.840.10008.5.1.4.1.1.104.1"]),
        "OT": (_("Other"), []),
        "DOC": (_("Document"), []),
    }

    #     "GM", _("General Microscopy"),
    #     "PX", _("Panoramic X-Ray"),
    #     "RT",
    #     "ECG",
    #     "VL",
    #     "MPR":  _("Multi-planar Reconstruction"),
    #     "CDA": _("Clinical Document Architecture")
    #     "STL",
    #     "OBJ",
    #     "MTL",
    #     "CAD",
    #     "3D",
    #     "XA": _("X-Ray Angiography")
    #     "XRF",
    #     "SEG",
    #     "REG",
    #     "KO", _("Key Object Selection")
