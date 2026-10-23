"""Suite-wide pytest hooks.

Language and install-dir chdir must run before any test module imports
product code that resolves locales or calls get_current_language_code.
"""

import os

from anonymizer.utils.logging import init_logging
from anonymizer.utils.translate import set_language_code
from tests.paths import REPO_ROOT

# Same install dir as anonymizer.main (relative assets/ paths resolve here).
_INSTALL_DIR = REPO_ROOT / "src" / "anonymizer"

pytest_plugins = ["tests.controller.tseg.fixtures"]


def pytest_sessionstart(session) -> None:
    """chdir to package install dir and latch UI language before collection."""
    os.chdir(_INSTALL_DIR)
    init_logging(file_handler=False)
    set_language_code("en_US")
