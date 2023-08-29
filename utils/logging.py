import os
import logging
import logging.handlers
from pydicom import config as pydicom_config

# TODO: investigate global, detachable log window with level and module filter / or delegate to OpenLogView app
LOGS_DIR = "/logs/"
LOG_FILENAME = "anonymizer.log"
LOG_SIZE = 1024 * 1024 * 20  # 20 MB
LOG_BACKUP_COUNT = 10
LOG_DEFAULT_LEVEL = logging.INFO
LOG_FORMAT = "{asctime} [{levelname}] {filename}:{lineno}: {message}"


def init_logging(install_dir: str) -> None:
    # TODO: provide UX to change log level
    logs_dir = install_dir + LOGS_DIR
    os.makedirs(logs_dir, exist_ok=True)
    # Get root logger:
    logger = logging.getLogger()
    # Setup rotating log file:
    logFormatter = logging.Formatter(LOG_FORMAT, style="{")
    fileHandler = logging.handlers.RotatingFileHandler(
        logs_dir + LOG_FILENAME, maxBytes=LOG_SIZE, backupCount=LOG_BACKUP_COUNT
    )
    fileHandler.setFormatter(logFormatter)
    logger.addHandler(fileHandler)
    # Setup stderr console output:
    consoleHandler = logging.StreamHandler()
    consoleHandler.setFormatter(logFormatter)
    logger.addHandler(consoleHandler)
    logger.setLevel(LOG_DEFAULT_LEVEL)

    logging.captureWarnings(True)

    # pydicom specific:
    pydicom_config.debug(LOG_DEFAULT_LEVEL == logging.DEBUG)
    pydicom_config.Settings.reading_validation_mode = pydicom_config.IGNORE

    # pynetdicom specific:
    pynetdicom_logger = logging.getLogger("pynetdicom")
    pynetdicom_logger.setLevel(logging.WARNING)


def set_log_level(level: int) -> None:
    logging.getLogger().setLevel(level)
