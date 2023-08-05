import os
import logging
import logging.handlers
from pydicom import config as pydicom_config
import customtkinter as ctk

# TODO: investigate global, detachable log window with level and module filter
LOGS_DIR = "/logs/"
LOG_FILENAME = "anonymizer.log"
LOG_SIZE = 1024 * 1024
LOG_BACKUP_COUNT = 10
LOG_DEFAULT_LEVEL = logging.DEBUG
LOG_FORMAT = "{asctime} {levelname} {module} {funcName}.{lineno} {message}"


def init_logging(install_dir: str) -> None:
    # TODO: move logging to utils.logging and allow setup from config.json
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
    # TODO: ensure it reflects UX setting
    pydicom_config.debug(LOG_DEFAULT_LEVEL == logging.DEBUG)


class TextBoxHandler(logging.Handler):
    def __init__(self, text):
        logging.Handler.__init__(self)
        self.text = text

    def emit(self, record):
        msg = self.format(record)
        self.text.configure(state="normal")
        self.text.insert(ctk.END, msg + "\n")
        self.text.configure(state="disabled")
        self.text.see(ctk.END)


# Install log handler for SCP Textbox:
def install_loghandler(logger, textbox: ctk.CTkTextbox) -> logging.Handler:
    handler = TextBoxHandler(textbox)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return handler
