import json
import os
from pathlib import Path


API_KEYS_PATH = Path("config/api_keys.json")


def get_config_value(name, default=""):
    """Read config from environment first, then config/api_keys.json."""
    env_value = os.getenv(name)

    if env_value:
        return env_value

    config = load_api_config()
    return config.get(name) or default


def get_int_config_value(name, default):
    value = get_config_value(name, default)

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_api_config():
    if not API_KEYS_PATH.exists():
        return {}

    try:
        with API_KEYS_PATH.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError):
        return {}
