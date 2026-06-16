import argparse
import logging
import sqlite3
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config.logging_config import setup_logging
from config.settings import BASE_DIR, DATA_DIR, DATABASE_PATH
from services.image_generator import _build_output_filename, create_news_card


setup_logging("crawler.log")
LOGGER = logging.getLogger("pnews.regenerate_all_cards")

GENERATED_PREFIX = "data/generated_images/"
UPLOAD_PREFIX = "data/uploads/"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Regenerate all stored news-card images with the latest branding."
    )
    parser.add_argument(
        "--status",
        default="all",
        help="Filter by article status: all, approved, pending, rejected, deleted.",
    )
    parser.add_argument(
        "--include-uploads",
        action="store_true",
        help="Also replace records currently pointing to uploaded images in data/uploads/.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum number of articles to process. Use 0 for all.",
    )
    parser.add_argument(
        "--date",
        default="",
        help="Only process articles whose derived date folder matches YYYY-MM-DD.",
    )
    return parser.parse_args()


def connect_db():
    conn = sqlite3.connect(DATABASE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def normalize_relative_media_path(value):
    raw = str(value or "").strip()
    if not raw or raw.startswith(("http://", "https://")):
        return ""

    path = Path(raw)
    if path.is_absolute():
        try:
            return str(path.resolve().relative_to(BASE_DIR.resolve())).replace("\\", "/")
        except ValueError:
            return ""

    candidate = (BASE_DIR / path).resolve()
    try:
        return str(candidate.relative_to(BASE_DIR.resolve())).replace("\\", "/")
    except ValueError:
        return ""


def pick_target_relative_path(article, include_uploads=False):
    for key in ("generated_poster_image", "image_path"):
        relative = normalize_relative_media_path(article.get(key))
        if relative.startswith(GENERATED_PREFIX):
            return relative
        if include_uploads and relative.startswith(UPLOAD_PREFIX):
            return relative
    return ""


def has_upload_backed_media(article):
    for key in ("generated_poster_image", "image_path"):
        relative = normalize_relative_media_path(article.get(key))
        if relative.startswith(UPLOAD_PREFIX):
            return True
    return False


def derive_date_folder(article):
    for key in ("crawled_at", "published_at", "created_at", "approved_at", "updated_at"):
        value = str(article.get(key) or "").strip()
        if len(value) >= 10:
            date_part = value[:10]
            if len(date_part) == 10 and date_part[4] == "-" and date_part[7] == "-":
                return date_part
    return "uncategorized"


def build_new_target_relative_path(article):
    date_folder = derive_date_folder(article)
    filename = _build_output_filename(article, index=None)
    return f"{GENERATED_PREFIX}{date_folder}/{filename}"


def fetch_articles(conn, status, limit):
    sql = "SELECT * FROM articles"
    params = []
    if status != "all":
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY id ASC"
    if limit and limit > 0:
        sql += " LIMIT ?"
        params.append(int(limit))
    return conn.execute(sql, params).fetchall()


def filter_rows_by_date(rows, target_date):
    value = str(target_date or "").strip()
    if not value:
        return list(rows)
    return [row for row in rows if derive_date_folder(dict(row)) == value]


def regenerate_article(article, include_uploads=False):
    article_dict = dict(article)
    current_relative = pick_target_relative_path(article_dict, include_uploads=include_uploads)
    if has_upload_backed_media(article_dict) and not include_uploads and not current_relative:
        return "skipped_upload", ""

    target_relative = current_relative or build_new_target_relative_path(article_dict)
    target_path = BASE_DIR / target_relative
    target_path.parent.mkdir(parents=True, exist_ok=True)

    create_news_card(article_dict, str(target_path))
    return "regenerated", target_relative


def update_article_paths(conn, article_id, relative_path):
    conn.execute(
        """
        UPDATE articles
        SET image_path = ?, generated_poster_image = ?, updated_at = datetime('now', 'localtime')
        WHERE id = ?
        """,
        (relative_path, relative_path, int(article_id)),
    )


def main():
    args = parse_args()
    valid_statuses = {"all", "approved", "pending", "rejected", "deleted"}
    status = str(args.status or "all").strip().lower()
    if status not in valid_statuses:
        raise SystemExit(f"Unsupported --status value: {status}")

    if not DATABASE_PATH.exists():
        raise SystemExit(f"Database not found: {DATABASE_PATH}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "generated_images").mkdir(parents=True, exist_ok=True)

    processed = 0
    updated = 0
    skipped_uploads = 0
    failures = 0

    with connect_db() as conn:
        rows = fetch_articles(conn, status=status, limit=args.limit)
        rows = filter_rows_by_date(rows, args.date)
        LOGGER.info("Found %s article(s) to inspect.", len(rows))

        for row in rows:
            article = dict(row)
            processed += 1
            article_id = int(article["id"])
            title = article.get("title", "")

            try:
                result, relative_path = regenerate_article(article, include_uploads=args.include_uploads)
                if result == "skipped_upload":
                    skipped_uploads += 1
                    LOGGER.info("Skipped upload-backed article #%s: %s", article_id, title)
                    continue

                update_article_paths(conn, article_id, relative_path)
                updated += 1
                LOGGER.info("Regenerated article #%s -> %s | %s", article_id, relative_path, title)
            except Exception as exc:
                failures += 1
                LOGGER.exception("Failed to regenerate article #%s (%s): %s", article_id, title, exc)

        conn.commit()

    LOGGER.info(
        "Done regenerating cards. processed=%s updated=%s skipped_uploads=%s failures=%s",
        processed,
        updated,
        skipped_uploads,
        failures,
    )


if __name__ == "__main__":
    main()
