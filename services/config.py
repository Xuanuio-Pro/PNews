import json
import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
API_KEYS_PATH = Path("config/api_keys.json")
ENV_PATH = BASE_DIR / ".env"


def load_env_file(path=ENV_PATH):
    """Load local .env values without overriding real environment variables."""
    env_path = Path(path)
    if not env_path.is_absolute():
        env_path = BASE_DIR / env_path
    if not env_path.exists():
        return

    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def get_config_value(name, default=""):
    """Read config from environment first, then config/api_keys.json."""
    load_env_file()
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
