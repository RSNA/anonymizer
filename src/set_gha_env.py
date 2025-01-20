# Run from github actions to set the version in the environment file to be accessed from build.yml release step

import os
import importlib.metadata

env_file = os.getenv("GITHUB_ENV")

if env_file is not None:
    with open(env_file, "a", encoding="utf-8") as f:
        f.write(f"version={importlib.metadata.version("anonymizer")}")
