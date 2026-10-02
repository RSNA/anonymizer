"""Shared numeric / charset limits for project settings (GUI + MCP).

Keep in sync with SettingsDialog / NetworkTimeoutsDialog / DICOMNodeDialog.
``ux_fields`` re-exports the network address constants for keystroke widgets.
"""

from __future__ import annotations

import string

# Identity (SettingsDialog)
PROJECT_NAME_MIN_CHARS = 3
PROJECT_NAME_MAX_CHARS = 20
# GUI keystroke charset is uppercase-only; MCP accepts either case for letters.
PROJECT_NAME_CHARSET = string.digits + string.ascii_letters + " -."
SITE_ID_MIN_CHARS = 3
SITE_ID_MAX_CHARS = 20
SITE_ID_CHARSET = string.digits + "-."
UID_ROOT_MIN_CHARS = 3
UID_ROOT_MAX_CHARS = 30
UID_ROOT_CHARSET = string.digits + "."

# Network addresses (ux_fields / DICOMNodeDialog)
IP_MIN_CHARS = 7
IP_MAX_CHARS = 15
IP_CHARSET = string.digits + "."
AET_MIN_CHARS = 3
AET_MAX_CHARS = 16
AET_CHARSET = string.ascii_letters + string.digits + " !#$%&()#*+-.,:;_^@?~|"
IP_PORT_MIN = 104
IP_PORT_MAX = 65535
HTTP_PATH_MIN_CHARS = 1
HTTP_PATH_MAX_CHARS = 255
HTTP_PATH_CHARSET = string.ascii_letters + string.digits + "/-_~.%"

# Network timeouts in seconds (NetworkTimeoutsDialog)
TCP_TIMEOUT_MIN = 0
TCP_TIMEOUT_MAX = 15
ACSE_TIMEOUT_MIN = 0
ACSE_TIMEOUT_MAX = 120
DIMSE_TIMEOUT_MIN = 0
DIMSE_TIMEOUT_MAX = 120
NETWORK_TIMEOUT_MIN = 0
NETWORK_TIMEOUT_MAX = 600
