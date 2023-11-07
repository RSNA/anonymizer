import os
import logging
import logging.handlers
from pydicom import config as pydicom_config

LOGS_DIR = "/logs/"
LOG_FILENAME = "anonymizer.log"
LOG_SIZE = 1024 * 1024 * 60  # 60 MB
LOG_BACKUP_COUNT = 10
LOG_DEFAULT_LEVEL = logging.INFO
# LOG_FORMAT = "{asctime} [{levelname}] {filename}:{lineno}: {message}"
LOG_FORMAT = "{asctime} {levelname} {module}.{funcName}.{lineno} {message}"


def init_logging(install_dir: str, debug_mode: bool) -> None:
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

    logging.captureWarnings(True)
    pydicom_config.settings.reading_validation_mode = pydicom_config.IGNORE

    set_log_level(LOG_DEFAULT_LEVEL if not debug_mode else logging.DEBUG)

def set_log_level(level: int) -> None:
    logging.getLogger().setLevel(level)

    # pydicom specific:
    # pydicom_config.debug(level == logging.DEBUG) # this is very low level tracing
    
    # Only enable pynetdicom logging for DEBUG level:
    pynetdicom_logger = logging.getLogger("pynetdicom")
    if level == logging.DEBUG:
        pynetdicom_logger.setLevel(level)
    else:
        pynetdicom_logger.setLevel(logging.WARNING)
