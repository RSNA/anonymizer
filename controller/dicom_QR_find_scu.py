import logging
from pathlib import Path
import customtkinter as ctk

from pydicom._version import __version__ as pydicom_version
from pydicom.uid import UID

from pynetdicom._version import __version__ as pynetdicom_version

logger = logging.getLogger(__name__)
