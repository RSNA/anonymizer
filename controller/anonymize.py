import logging
from pydicom import dcmread, Dataset

logger = logging.getLogger(__name__)

_tag_ops = {}
_tag_keep = {}


# Anonymization functions for each script operation
def hash_date(date: str) -> str:
    return date


# TODO: functions to handle @param(), @integer()


def init(script) -> bool:
    # Parse the anonymize script and create a dictionary of tags to keep
    # and tags to transform using the anonymization function indicated by the script operation
    return True


def anonymize_dataset(ds: Dataset, anon_id: str, anon_name: str) -> Dataset:
    # To create an anonymized dataset:
    # Iterate through each tag in _tag_keep and copy ds[tag] to the new dataset
    # Iterate through each tag from _tags_ops and apply the relevant anonymization function on ds[tag]
    return ds
