from ast import Tuple
import logging
import model.project as project
from pydicom import dcmread, Dataset

_tag_ops = {}
_tag_keep = {}


# Patient Mapping Function:
def get_anon_patient(name: str, id: str) -> tuple:
    # Create/Manage lookup table per project for mapping Actual to Anonymized Patient
    # TODO: patient index store
    return ("ANON_NAME", "ANON_ID")


# Anonymization functions for each script operation
def _hash_date(date: str) -> str:
    return date


# TODO: functions to handle @param(), @integer()


def init(script) -> bool:
    # Parse the anonymize script and create a dict of tags to keep
    # and dict of tags to transform using the anonymization function indicated by the script operation
    return True


def anonymize_dataset(ds: Dataset) -> Dataset:
    # To create an anonymized dataset:
    #   Get Anon_PatientName and Anon_PatientID for this patient
    #   Iterate through each tag in _tag_keep and copy ds[tag] to the new dataset
    #   Iterate through each tag from _tags_ops and apply the relevant anonymization function on ds[tag]
    return ds
