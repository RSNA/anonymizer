import logging

from pydicom import config as pydicom_config

from anonymizer.model.project import LoggingLevels
from src.anonymizer.utils.logging import (
    disable_pydicom_debug,
    enable_pydicom_debug,
    set_anonymizer_log_level,
    set_logging_levels,
    set_pynetdicom_log_level,
)


def test_set_logging_levels_all_levels():
    """
    Test setting all logging levels.
    """
    levels = LoggingLevels(logging.DEBUG, logging.INFO, True, False, False)

    set_logging_levels(levels)

    assert logging.getLogger().getEffectiveLevel() == logging.DEBUG
    assert logging.getLogger("pynetdicom").getEffectiveLevel() == logging.INFO


def test_set_logging_levels_no_pydicom_debug():
    """
    Test setting logging levels without pydicom debug.
    """
    levels = LoggingLevels(logging.WARNING, logging.ERROR, False, False, False)

    set_logging_levels(levels)

    assert logging.getLogger().getEffectiveLevel() == logging.WARNING
    assert logging.getLogger("pynetdicom").getEffectiveLevel() == logging.ERROR


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


def test_enable_pydicom_debug():
    """
    Test disabling pydicom debug mode.
    """
    enable_pydicom_debug()
    assert pydicom_config.debugging


def test_disable_pydicom_debug():
    """
    Test disabling pydicom debug mode.
    """
    disable_pydicom_debug()
    assert not pydicom_config.debugging
