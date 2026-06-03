import sqlite3
import sys
import logging
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Cấu hình logging ghi vào logs/crawler.log và console
from config.logging_config import setup_logging
setup_logging("crawler.log")
LOGGER = logging.getLogger("pnews.sync")

import web_app


def count_articles():
    db_path = Path("data/cms.sqlite3")
    if not db_path.exists():
        return 0

    try:
        with sqlite3.connect(db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    except sqlite3.Error as e:
        LOGGER.error(f"Lỗi khi truy cập database để đếm bài viết: {str(e)}")
        return 0


def main():
    try:
        before = count_articles()
        web_app.init_db()
        after = count_articles()
        added = max(after - before, 0)
        LOGGER.info(f"Đã sync CMS từ data/exports/articles.csv: trước={before}, sau={after}, thêm mới={added}")
    except Exception as e:
        LOGGER.error(f"Lỗi khi thực hiện đồng bộ CMS từ CSV: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
