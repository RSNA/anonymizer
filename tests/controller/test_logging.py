from src.anonymizer.utils.logging import (
    disable_pydicom_debug,
    enable_pydicom_debug,
    set_logging_levels, 
    set_anonymizer_log_level,
    set_pynetdicom_log_level,
)
from anonymizer.model.project import LoggingLevels
import logging
import logging.handlers
from pydicom import config as pydicom_config

def test_set_logging_levels_all_levels():
    """
    Test setting all logging levels.
    """
    levels = LoggingLevels(logging.DEBUG, logging.INFO, True)

    set_logging_levels(levels)

    assert logging.getLogger().getEffectiveLevel() == logging.DEBUG
    assert logging.getLogger("pynetdicom").getEffectiveLevel() == logging.INFO
    # assert pydicom_config.debug()

def test_set_logging_levels_no_pydicom_debug():
    """
    Test setting logging levels without pydicom debug.
    """
    levels = LoggingLevels(logging.WARNING, logging.ERROR, False)

    set_logging_levels(levels)

    assert logging.getLogger().getEffectiveLevel() == logging.WARNING
    assert logging.getLogger("pynetdicom").getEffectiveLevel() == logging.ERROR
    # assert not pydicom_config.debug()

def test_set_anonymizer_log_level():
    """
    Test setting the anonymizer log level.
    """
    set_anonymizer_log_level(logging.INFO)
    assert logging.getLogger().getEffectiveLevel() == logging.INFO

def test_set_pynetdicom_log_level():
    """
    Test setting the pynetdicom log level.
    """
    set_pynetdicom_log_level(logging.DEBUG)
    assert logging.getLogger("pynetdicom").getEffectiveLevel() == logging.DEBUG

def test_disable_pydicom_debug():
    """
    Test disabling pydicom debug mode.
    """
    disable_pydicom_debug()
    assert not pydicom_config.debug()