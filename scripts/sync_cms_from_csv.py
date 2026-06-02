import sqlite3
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import web_app


def count_articles():
    db_path = Path("data/cms.sqlite3")
    if not db_path.exists():
        return 0

    try:
        with sqlite3.connect(db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    except sqlite3.Error:
        return 0


def main():
    before = count_articles()
    web_app.init_db()
    after = count_articles()
    added = max(after - before, 0)
    print(f"Da sync CMS tu data/exports/articles.csv: truoc={before}, sau={after}, them_moi={added}")


if __name__ == "__main__":
    main()
