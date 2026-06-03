import os
from pathlib import Path
from services.config import get_config_value, load_env_file

# Nạp file cấu hình .env (chỉ làm một lần)
load_env_file()

APP_ENV = get_config_value("PNEWS_APP_ENV", "production")
HOST = get_config_value("PNEWS_HOST", "0.0.0.0")

try:
    PORT = int(get_config_value("PNEWS_PORT", "8000"))
except (ValueError, TypeError):
    PORT = 8000

# Thiết lập đường dẫn tương thích đa nền tảng
BASE_DIR = Path(__file__).resolve().parents[1]

# Chuyển đổi các cấu hình đường dẫn sang pathlib.Path
data_dir_str = get_config_value("PNEWS_DATA_DIR", "data")
DATA_DIR = Path(data_dir_str)
if not DATA_DIR.is_absolute():
    DATA_DIR = BASE_DIR / DATA_DIR

log_dir_str = get_config_value("PNEWS_LOG_DIR", "logs")
LOG_DIR = Path(log_dir_str)
if not LOG_DIR.is_absolute():
    LOG_DIR = BASE_DIR / LOG_DIR

db_path_str = get_config_value("PNEWS_DATABASE_PATH", "data/cms.sqlite3")
DATABASE_PATH = Path(db_path_str)
if not DATABASE_PATH.is_absolute():
    DATABASE_PATH = BASE_DIR / DATABASE_PATH

ADMIN_ACCOUNTS_RAW = get_config_value("PNEWS_ADMIN_ACCOUNTS", "")
FACEBOOK_PAGE_ID = get_config_value("FACEBOOK_PAGE_ID", "")
FACEBOOK_PAGE_ACCESS_TOKEN = get_config_value("FACEBOOK_PAGE_ACCESS_TOKEN", "")
FACEBOOK_GRAPH_API_VERSION = get_config_value("FACEBOOK_GRAPH_API_VERSION", "v25.0")
TELEGRAM_BOT_TOKEN = get_config_value("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = get_config_value("TELEGRAM_CHAT_ID", "")
GEMINI_API_KEY = get_config_value("GEMINI_API_KEY", "")
GROQ_API_KEY = get_config_value("GROQ_API_KEY", "")
