# Run from github actions to set the version in the environment file to be accessed in from build.yml release step

import os

from __version__ import __version__

env_file = os.getenv("GITHUB_ENV")

with open(env_file, "a") as f:
    f.write(f"version={__version__}")
