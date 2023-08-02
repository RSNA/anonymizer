# UNIT TESTS for controller/anonymize.py
# use pytest from terminal to show full logging output
import logging
from controller.anonymize import _hash_date

logger = logging.getLogger(__name__)


def test_hash_datet1():
    logger.info("Testing _hash_date() function")
    # Test hash_date() with a date string
    date = "2021-01-01"
    hashed_date = _hash_date(date)
    assert hashed_date == "2021-01-01"
