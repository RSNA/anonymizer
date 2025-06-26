"""
This module provides functions for initializing and configuring logging in the application.

Functions:
- _get_logs_dir(run_as_exe: bool, install_dir: str) -> str: Returns the directory path where logs should be stored based on the platform and execution mode.
- init_logging(install_dir: str, run_as_exe: bool, file_handler: bool = True) -> str: Initializes the logging configuration for the application.
- set_logging_levels(levels: LoggingLevels): Sets the logging levels for different components of the application.
- set_anonymizer_log_level(level: int) -> None: Sets the log level for the anonymizer.
- set_pynetdicom_log_level(level: int) -> None: Sets the log level for pynetdicom.
- enable_pydicom_debug() -> None: Enables debug mode for pydicom.
- disable_pydicom_debug() -> None: Disables debug mode for pydicom.
"""

import logging
import logging.handlers
import os
from pathlib import Path

from pydicom import config as pydicom_config

from anonymizer.model.project import LoggingLevels
from anonymizer.utils.translate import _

LOG_FILENAME = "anonymizer.log"
LOG_SIZE = 1024 * 1024 * 100  # 100 MB
LOG_BACKUP_COUNT = 10
LOG_DEFAULT_LEVEL = logging.DEBUG
LOG_FORMAT = "{asctime} {levelname} {threadName} {name}.{funcName}.{lineno} {message}"


def _get_logs_dir() -> str:
    """
    Returns the directory path where logs should be stored based on the platform and execution mode.

    Returns:
        str: The directory path where logs should be stored.

    """
    return str(Path.home() / _("Documents").strip() / _("RSNA Anonymizer").strip() / _("logs").strip())
    # if run_as_exe:
    #     if platform.system() == "Windows":
    #         return os.path.join(os.path.expanduser("~"), "AppData", "Local", "Anonymizer", "Logs")
    #     elif platform.system() == "Darwin":
    #         return os.path.join(os.path.expanduser("~"), "Library", "Logs", "Anonymizer")
    #     elif platform.system() == "Linux":
    #         return os.path.join(os.path.expanduser("~"), "Anonymizer", "Logs")
    #     else:
    #         raise RuntimeError("Unsupported platform")
    # else:
    #     return os.path.join(install_dir, "logs")


def init_logging(file_handler: bool = True) -> str | None:
    """
    Initializes the logging configuration for the application.

    Args:
        file_handler (bool, optional): Indicates whether to set up a rotating log file handler.
            Defaults to True.

    Returns:
        logs_dir (str): The directory path where logs are stored if file_handler is True, otherwise None.
    """
    # Get root logger:
    logger = logging.getLogger()
    logFormatter = logging.Formatter(LOG_FORMAT, style="{")
    logs_dir = None

    if file_handler:
        logs_dir = _get_logs_dir()
        os.makedirs(logs_dir, exist_ok=True)
        logger.info("Logs will be stored in: %s", logs_dir)
        # Setup rotating log file:
        fileHandler = logging.handlers.RotatingFileHandler(
            os.path.join(logs_dir, LOG_FILENAME), maxBytes=LOG_SIZE, backupCount=LOG_BACKUP_COUNT
        )
        fileHandler.setFormatter(logFormatter)
        logger.addHandler(fileHandler)

    # Setup stderr console output:
    consoleHandler = logging.StreamHandler()
    consoleHandler.setFormatter(logFormatter)
    logger.addHandler(consoleHandler)

    logging.captureWarnings(True)
    pydicom_config.settings.reading_validation_mode = pydicom_config.IGNORE

    set_anonymizer_log_level(LOG_DEFAULT_LEVEL)
    # by default set pynetdicom to WARNING level
    # (pynetdicom._config.LOG_HANDLER_LEVEL = "none" # disable pynetdicom logging, default is "standard")
    set_pynetdicom_log_level(logging.WARNING)
    # leave pydicom logging at default level, user can enable debug mode if needed
    logger.info("Logging initialized")
    return logs_dir


def set_logging_levels(levels: LoggingLevels):
    set_anonymizer_log_level(levels.anonymizer)
    set_pynetdicom_log_level(levels.pynetdicom)
    if levels.pydicom:
        enable_pydicom_debug()
    else:
        disable_pydicom_debug()


def set_anonymizer_log_level(level: int) -> None:
    """
    Set the log level for the anonymizer.

    Args:
        level (int): The log level to be set.

    Returns:
        None
    """
    logging.getLogger().setLevel(level)


def set_pynetdicom_log_level(level: int) -> None:
    """
    Set the log level for pynetdicom.

    Args:
        level (int): The log level to be set.

    Returns:
        None
    """
    logging.getLogger("pynetdicom").setLevel(level)


def enable_pydicom_debug() -> None:
    """
    Enable debug mode for pydicom.

    Returns:
        None
    """
    pydicom_config.debug(True)


def disable_pydicom_debug() -> None:
    """
    Disable debug mode for pydicom.

    Returns:
        None
    """
    pydicom_config.debug(False)
