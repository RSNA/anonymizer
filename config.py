# config.py
import json
import os

_CONFIG_FILE = "config.json"


def load(module_name) -> dict:
    # Default settings
    settings = {}

    # TODO: Integrity checking on configuration file, ensure valid json, etc.
    if os.path.isfile(_CONFIG_FILE):
        with open(_CONFIG_FILE, "r") as f:
            config = json.load(f)

        settings = config.get(module_name, {})

    return settings


def save(module_name, name, value):
    if os.path.isfile(_CONFIG_FILE):
        with open(_CONFIG_FILE, "r") as f:
            config_dict = json.load(f)
    else:
        config_dict = {}

    config_dict[module_name][name] = value

    with open(_CONFIG_FILE, "w") as f:
        json.dump(config_dict, f, indent=4)
