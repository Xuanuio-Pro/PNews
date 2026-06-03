import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
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
    """Read config from environment or the local .env file only."""
    load_env_file()
    env_value = os.getenv(name)

    if env_value:
        return env_value

    return default


def get_int_config_value(name, default):
    value = get_config_value(name, default)

    try:
        return int(value)
    except (TypeError, ValueError):
        return default
