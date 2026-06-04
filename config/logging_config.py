import logging
import logging.handlers
import os
from datetime import datetime

from config.settings import LOG_DIR


LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FORMAT = "[%(asctime)s] %(levelname)s %(name)s (%(filename)s:%(lineno)d): %(message)s"
formatter = logging.Formatter(LOG_FORMAT)


def _add_rotating_file_handler(root_logger, file_path, level):
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            file_path, maxBytes=10*1024*1024, backupCount=5, encoding="utf-8"
        )
    except OSError as exc:
        fallback_name = (
            f"{file_path.stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-"
            f"{os.getpid()}{file_path.suffix}"
        )
        fallback_path = file_path.with_name(fallback_name)
        try:
            file_handler = logging.handlers.RotatingFileHandler(
                fallback_path, maxBytes=10*1024*1024, backupCount=5, encoding="utf-8"
            )
        except OSError:
            root_logger.warning(
                "Khong the mo file log %s: %s. Tiep tuc ghi log ra console.",
                file_path,
                exc,
            )
            return

        root_logger.warning(
            "Khong the mo file log %s: %s. Chuyen sang file log tam thoi %s.",
            file_path,
            exc,
            fallback_path,
        )

    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    root_logger.addHandler(file_handler)


def setup_logging(log_filename="app.log"):
    root_logger = logging.getLogger()

    if root_logger.hasHandlers():
        return

    root_logger.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)

    _add_rotating_file_handler(root_logger, LOG_DIR / log_filename, logging.INFO)
    _add_rotating_file_handler(root_logger, LOG_DIR / "error.log", logging.WARNING)
