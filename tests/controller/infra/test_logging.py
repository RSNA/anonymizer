import io
import logging

from pydicom import config as pydicom_config

from anonymizer.model.project import LoggingLevels
from anonymizer.utils.logging import (
    _EncodingSafeStreamHandler,
    disable_pydicom_debug,
    enable_pydicom_debug,
    set_anonymizer_log_level,
    set_logging_levels,
    set_pynetdicom_log_level,
)


def test_encoding_safe_stream_handler_replaces_unencodable_chars() -> None:
    """Windows cp1252 consoles must not raise on Unicode arrows in log lines."""
    buf = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    handler = _EncodingSafeStreamHandler(buf)
    handler.setFormatter(logging.Formatter("%(message)s"))
    log = logging.getLogger("test_encoding_safe_stream_handler")
    log.handlers.clear()
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False

    log.info("geometry \u2192 TS seg")  # arrow that cp1252 cannot encode
    buf.seek(0)
    text = buf.read()
    assert "geometry" in text
    assert "TS seg" in text


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
