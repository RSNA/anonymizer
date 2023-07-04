import logging

logger = logging.getLogger(__name__)


def start():
    logging.info("start")
    return True


def stop():
    logging.info("stop")
    return True
