# config.py
import json
import os

_CONFIG_FILE = "model/config.json"


def load(module_name) -> dict:
    # Default settings
    settings = {}

    # TODO: Integrity checking on configuration file, ensure valid json, etc.
    if os.path.isfile(_CONFIG_FILE):
        with open(_CONFIG_FILE, "r") as f:
            config = json.load(f)

        settings = config.get(module_name, {})

    return settings


def save(module_name: str, name: str, value) -> None:
    if os.path.isfile(_CONFIG_FILE):
        with open(_CONFIG_FILE, "r") as f:
            config_dict = json.load(f)
    else:
        config_dict = {}

    # Ensure module_name exists in config_dict:
    config_dict.setdefault(module_name, {})

    config_dict[module_name][name] = value

    with open(_CONFIG_FILE, "w") as f:
        json.dump(config_dict, f, indent=4)


def save_bulk(module_name: str, settings: dict) -> None:
    if os.path.isfile(_CONFIG_FILE):
        with open(_CONFIG_FILE, "r") as f:
            config_dict = json.load(f)
    else:
        config_dict = {}

    # Ensure module_name exists in config_dict:
    config_dict.setdefault(module_name, {})

    config_dict[module_name].update(settings)

    with open(_CONFIG_FILE, "w") as f:
        json.dump(config_dict, f, indent=4)
