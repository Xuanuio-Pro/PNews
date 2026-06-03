from pathlib import Path

from services.config import get_config_value, load_env_file

# Nạp file cấu hình .env (chỉ làm một lần)
load_env_file()

BASE_DIR = Path(__file__).resolve().parents[1]


def _resolve_project_path(value, default):
    path = Path(str(value or default))
    if not path.is_absolute():
        path = BASE_DIR / path
    return path

APP_ENV = get_config_value("PNEWS_APP_ENV", "production")
HOST = get_config_value("PNEWS_HOST", "0.0.0.0")

try:
    PORT = int(get_config_value("PNEWS_PORT", "8000"))
except (ValueError, TypeError):
    PORT = 8000

# Chuyển đổi các cấu hình đường dẫn sang pathlib.Path tuyệt đối.
DATA_DIR = _resolve_project_path(get_config_value("PNEWS_DATA_DIR", "data"), "data")
LOG_DIR = _resolve_project_path(get_config_value("PNEWS_LOG_DIR", "logs"), "logs")
DATABASE_PATH = _resolve_project_path(
    get_config_value("PNEWS_DATABASE_PATH", "data/cms.sqlite3"),
    "data/cms.sqlite3",
)

ADMIN_ACCOUNTS_RAW = get_config_value("PNEWS_ADMIN_ACCOUNTS", "")
FACEBOOK_PAGE_ID = get_config_value("FACEBOOK_PAGE_ID", "")
FACEBOOK_PAGE_ACCESS_TOKEN = get_config_value("FACEBOOK_PAGE_ACCESS_TOKEN", "")
FACEBOOK_GRAPH_API_VERSION = get_config_value("FACEBOOK_GRAPH_API_VERSION", "v25.0")
TELEGRAM_BOT_TOKEN = get_config_value("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = get_config_value("TELEGRAM_CHAT_ID", "")
GEMINI_API_KEY = get_config_value("GEMINI_API_KEY", "")
GROQ_API_KEY = get_config_value("GROQ_API_KEY", "")


def resolve_project_path(path):
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return BASE_DIR / candidate


def resolve_data_path(path):
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    parts = candidate.parts
    if parts and parts[0] == "data":
        return DATA_DIR.joinpath(*parts[1:])
    return BASE_DIR / candidate


def ensure_runtime_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "generated_images").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "uploads").mkdir(parents=True, exist_ok=True)
