import os, sys
import logging
from __version__ import __version__
from pydicom._version import __version__ as pydicom_version
from pynetdicom._version import __version__ as pynetdicom_version

import tkinter as tk
import customtkinter as ctk

from utils.logging import init_logging

logger = logging.getLogger()


def main():
    args = str(sys.argv)
    install_dir = os.path.dirname(os.path.realpath(__file__))
    run_as_exe = getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")
    logs_dir = init_logging(install_dir, run_as_exe)
    os.chdir(install_dir)

    logger.info(f"cmd line args={args}")

    if run_as_exe:
        logger.info(f"Running as PyInstaller executable")

    logger.info(f"Python Optimization Level [0,1,2]: {sys.flags.optimize}")
    logger.info(f"Starting ANONYMIZER Version {__version__}")
    logger.info(f"Running from {os.getcwd()}")
    logger.info(f"Python Version: {sys.version_info.major}.{sys.version_info.minor}")
    logger.info(f"tkinter TkVersion: {tk.TkVersion} TclVersion: {tk.TclVersion}")
    logger.info(f"Customtkinter Version: {ctk.__version__}")
    logger.info(f"pydicom Version: {pydicom_version}, pynetdicom Version: {pynetdicom_version}")

    # Close Pyinstaller startup splash image on Windows
    if sys.platform.startswith("win"):
        try:
            import pyi_splash  # type: ignore

            pyi_splash.close()  # type: ignore
        except Exception:
            pass


if __name__ == "__main__":
    main()
