# Run from github actions to set the version in the environment file to be accessed in from build.yml release step

import os

from __version__ import __version__

env_file = os.getenv("GITHUB_ENV")

if env_file is not None:
    with open(env_file, "a", encoding="utf-8") as f:
        f.write(f"version={__version__}")
