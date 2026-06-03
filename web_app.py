import csv
import hashlib
import html
import io
import json
import logging
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
import unicodedata
from datetime import datetime
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from PIL import Image

from services.article_search import find_rendered_image
from services.chatbot_service import CHAT_SUGGESTIONS, handle_chat_message, init_chat_logs
from services.facebook_service import (
    FacebookAPIError,
    FacebookConfigError,
    FacebookPublishError,
    buildFacebookCaption,
    getPostInfo,
    publishMultiPhotoPost,
    publishPhotoPost,
)
from services.config import get_config_value
from services.image_generator import generate_news_card
from services.notification_service import NotificationService
from config.settings import (
    ADMIN_ACCOUNTS_RAW,
    DATA_DIR,
    DATABASE_PATH,
    ensure_runtime_dirs,
)
from config.logging_config import setup_logging

# Khởi tạo hệ thống ghi log tập trung cho web app
setup_logging("app.log")
LOGGER = logging.getLogger("pnews.web")

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = DATABASE_PATH

UPLOAD_DIR = DATA_DIR / "uploads"
ASSET_DIR = BASE_DIR / "web_assets"
DEFAULT_THUMBNAIL = "PNews.png"
SITE_LOGO_URL = "/assets/pnews-logo.png"
ASSET_VERSION = str(int(time.time()))

def load_admin_accounts():
    raw_accounts = ADMIN_ACCOUNTS_RAW
    accounts = {}

    if raw_accounts:
        try:
            parsed_accounts = json.loads(raw_accounts)
        except json.JSONDecodeError:
            parsed_accounts = None

        if isinstance(parsed_accounts, dict):
            accounts.update(
                {
                    str(username): str(password)
                    for username, password in parsed_accounts.items()
                    if username and password
                }
            )
        else:
            for item in re.split(r"[;,]", raw_accounts):
                if ":" not in item:
                    continue
                username, password = item.split(":", 1)
                username = username.strip()
                password = password.strip()
                if username and password:
                    accounts[username] = password

    single_user = get_config_value("PNEWS_ADMIN_USER")
    single_password = get_config_value("PNEWS_ADMIN_PASSWORD")
    if single_user and single_password:
        accounts[single_user] = single_password

    return accounts


ADMIN_ACCOUNTS = load_admin_accounts()
SESSION_COOKIE = "pnews_cms_session"
SESSIONS = set()
CLIENT_PAGE_SIZE = 12
ADMIN_PAGE_SIZE = 10
CLIENT_TOPIC_ORDER = [
    "Tin tức chung",
    "Tin tức PTIT",
    "Giáo dục",
    "Khoa học - Công nghệ",
    "Kinh doanh",
    "Pháp luật",
    "Sức khỏe",
    "Thế giới",
    "Thể thao",
    "Thời sự",
    "Giải trí",
]

ARTICLE_COLUMNS = [
    "source",
    "title",
    "url",
    "crawled_at",
    "published_at",
    "thumbnail",
    "summary",
    "summary_source",
    "newspaper_type",
    "content_topic",
    "category",
]

DEPRECATED_SOURCES = {"Dân trí", "24h"}

STATUS_LABELS = {
    "pending": "Chờ duyệt",
    "approved": "Đã duyệt",
    "rejected": "Từ chối",
    "deleted": "Đã xóa",
}

FACEBOOK_STATUS_LABELS = {
    "not_posted": "Chưa đăng FB",
    "posting": "Đang đăng FB",
    "success": "Đã đăng FB",
    "failed": "Lỗi đăng FB",
}

ALLOWED_UPLOAD_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_iso_date():
    return datetime.now().strftime("%Y-%m-%d")


def slugify(value):
    value = str(value or "bài viết").replace("Đ", "D").replace("đ", "d")
    normalized = unicodedata.normalize("NFKD", value.lower())
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized or "bai-viet"


def escape(value):
    return html.escape("" if value is None else str(value), quote=True)


def connect_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with connect_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT DEFAULT '',
                title TEXT NOT NULL,
                url TEXT DEFAULT '',
                crawled_at TEXT DEFAULT '',
                published_at TEXT DEFAULT '',
                thumbnail TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                summary_source TEXT DEFAULT '',
                newspaper_type TEXT DEFAULT '',
                content_topic TEXT DEFAULT '',
                category TEXT DEFAULT '',
                image_path TEXT DEFAULT '',
                generated_poster_image TEXT DEFAULT '',
                approval_status TEXT NOT NULL DEFAULT 'pending',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                approved_at TEXT DEFAULT '',
                reviewed_at TEXT DEFAULT '',
                deleted_at TEXT DEFAULT '',
                facebook_posted INTEGER DEFAULT 0,
                facebook_post_id TEXT DEFAULT '',
                facebook_permalink TEXT DEFAULT '',
                facebook_published_at TEXT DEFAULT '',
                facebook_publish_status TEXT DEFAULT 'not_posted',
                facebook_publish_error TEXT DEFAULT '',
                facebook_caption TEXT DEFAULT ''
            )
            """
        )
        ensure_article_schema(conn)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_approval_status ON articles(approval_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_facebook_status ON articles(facebook_publish_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_topic ON articles(content_topic)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_status_published ON articles(status, published_at)"
        )
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_url ON articles(url) WHERE url != ''")
        conn.commit()
    init_chat_logs()
    seed_articles_from_csv()


def ensure_article_schema(conn):
    columns = get_table_columns(conn, "articles")
    migrations = {
        "published_at": "ALTER TABLE articles ADD COLUMN published_at TEXT DEFAULT ''",
        "approved_at": "ALTER TABLE articles ADD COLUMN approved_at TEXT DEFAULT ''",
        "approval_status": "ALTER TABLE articles ADD COLUMN approval_status TEXT DEFAULT 'pending'",
        "facebook_posted": "ALTER TABLE articles ADD COLUMN facebook_posted INTEGER DEFAULT 0",
        "facebook_post_id": "ALTER TABLE articles ADD COLUMN facebook_post_id TEXT DEFAULT ''",
        "facebook_permalink": "ALTER TABLE articles ADD COLUMN facebook_permalink TEXT DEFAULT ''",
        "facebook_published_at": "ALTER TABLE articles ADD COLUMN facebook_published_at TEXT DEFAULT ''",
        "facebook_publish_status": "ALTER TABLE articles ADD COLUMN facebook_publish_status TEXT DEFAULT 'not_posted'",
        "facebook_publish_error": "ALTER TABLE articles ADD COLUMN facebook_publish_error TEXT DEFAULT ''",
        "facebook_caption": "ALTER TABLE articles ADD COLUMN facebook_caption TEXT DEFAULT ''",
        "generated_poster_image": "ALTER TABLE articles ADD COLUMN generated_poster_image TEXT DEFAULT ''",
    }

    for column, sql in migrations.items():
        if column not in columns:
            conn.execute(sql)

    columns = get_table_columns(conn, "articles")

    conn.execute(
        """
        UPDATE articles
        SET published_at = COALESCE(NULLIF(published_at, ''), NULLIF(crawled_at, ''), created_at)
        WHERE published_at IS NULL OR TRIM(published_at) = ''
        """
    )
    conn.execute(
        """
        UPDATE articles
        SET approved_at = COALESCE(NULLIF(approved_at, ''), NULLIF(reviewed_at, ''))
        WHERE status = 'approved' AND (approved_at IS NULL OR TRIM(approved_at) = '')
        """
    )
    conn.execute(
        """
        UPDATE articles
        SET approval_status = CASE
            WHEN status IN ('pending', 'approved', 'rejected') THEN status
            ELSE COALESCE(NULLIF(approval_status, ''), 'pending')
        END
        WHERE approval_status IS NULL OR TRIM(approval_status) = ''
        """
    )
    conn.execute(
        """
        UPDATE articles
        SET approval_status = status
        WHERE status IN ('pending', 'approved', 'rejected')
          AND COALESCE(NULLIF(TRIM(approval_status), ''), '') != status
        """
    )
    conn.execute(
        """
        UPDATE articles
        SET facebook_publish_status = CASE
            WHEN COALESCE(facebook_posted, 0) = 1 THEN 'success'
            ELSE 'not_posted'
        END
        WHERE facebook_publish_status IS NULL OR TRIM(facebook_publish_status) = ''
        """
    )
    conn.execute(
        """
        UPDATE articles
        SET generated_poster_image = COALESCE(NULLIF(generated_poster_image, ''), NULLIF(image_path, ''), '')
        WHERE (generated_poster_image IS NULL OR TRIM(generated_poster_image) = '')
          AND image_path IS NOT NULL
          AND TRIM(image_path) != ''
        """
    )


def seed_articles_from_csv():
    csv_path = DATA_DIR / "exports" / "articles.csv"
    if not csv_path.exists():
        return

    generated_images = find_generated_images()

    with connect_db() as conn:
        existing_urls = {
            row["url"]: row["id"]
            for row in conn.execute("SELECT id, url FROM articles WHERE url != ''")
        }
        with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                if is_deprecated_source(row.get("source", "")):
                    continue

                url = row.get("url", "").strip()
                title = row.get("title", "").strip()
                if not title:
                    continue

                image_path = match_generated_image(title, generated_images)
                values = {column: row.get(column, "") for column in ARTICLE_COLUMNS}
                values["image_path"] = image_path
                values["generated_poster_image"] = image_path
                values["created_at"] = now_iso()
                values["updated_at"] = values["created_at"]

                if url and url in existing_urls:
                    conn.execute(
                        """
                        UPDATE articles
                        SET
                            published_at = CASE
                                WHEN published_at IS NULL OR TRIM(published_at) = '' THEN :published_at
                                ELSE published_at
                            END,
                            crawled_at = CASE
                                WHEN crawled_at IS NULL OR TRIM(crawled_at) = '' THEN :crawled_at
                                ELSE crawled_at
                            END,
                            summary_source = CASE
                                WHEN summary_source IS NULL OR TRIM(summary_source) = '' THEN :summary_source
                                ELSE summary_source
                            END,
                            image_path = CASE
                                WHEN image_path IS NULL OR TRIM(image_path) = '' THEN :image_path
                                ELSE image_path
                            END,
                            generated_poster_image = CASE
                                WHEN generated_poster_image IS NULL OR TRIM(generated_poster_image) = '' THEN :generated_poster_image
                                ELSE generated_poster_image
                            END
                        WHERE id = :id
                        """,
                        {**values, "id": existing_urls[url]},
                    )
                    continue

                conn.execute(
                    """
                    INSERT INTO articles (
                        source, title, url, crawled_at, published_at, thumbnail, summary,
                        summary_source, newspaper_type, content_topic, category,
                        image_path, generated_poster_image, created_at, updated_at
                    ) VALUES (
                        :source, :title, :url, :crawled_at, :published_at, :thumbnail, :summary,
                        :summary_source, :newspaper_type, :content_topic, :category,
                        :image_path, :generated_poster_image, :created_at, :updated_at
                    )
                    """,
                    values,
                )
                if url:
                    existing_urls[url] = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.commit()


def is_deprecated_source(source):
    return str(source or "").strip() in DEPRECATED_SOURCES


def find_generated_images():
    image_root = DATA_DIR / "generated_images"
    if not image_root.exists():
        return []
    paths = []
    for extension in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
        paths.extend(image_root.rglob(extension))
    return sorted(paths, key=lambda path: path.stat().st_mtime, reverse=True)


def match_generated_image(title, generated_images):
    title_slug = slugify(title)
    for image_path in generated_images:
        if title_slug and title_slug in image_path.stem:
            return str(image_path.relative_to(BASE_DIR)).replace("\\", "/")
    return ""


def to_relative_media_path(path_or_url):
    value = str(path_or_url or "").strip()
    if not value or value.startswith(("http://", "https://")):
        return ""

    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path

    if not path.exists() or not path.is_file():
        return ""

    try:
        return str(path.resolve().relative_to(BASE_DIR.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve()).replace("\\", "/")


def ensure_generated_image_for_article(article_id):
    updated = ensure_generated_images_for_articles([article_id])
    if not updated:
        return ""
    article = get_article(article_id)
    return str(article["image_path"] or "") if article else ""


def resolve_article_export_image(article):
    if not article or article["status"] != "approved":
        return None

    image_path = to_relative_media_path(article["image_path"])
    if not image_path:
        ensure_generated_image_for_article(article["id"])
        refreshed = get_article(article["id"])
        if refreshed:
            article = refreshed
            image_path = to_relative_media_path(article["image_path"])

    if not image_path:
        image_path = find_rendered_image(article["title"])

    if not image_path:
        return None

    target = (BASE_DIR / image_path).resolve()
    try:
        target.relative_to(BASE_DIR.resolve())
    except ValueError:
        return None
    if not target.exists() or not target.is_file():
        return None
    return target


def resolve_article_facebook_image(article):
    if not article:
        return None, None

    article_id = int(article["id"])
    ensure_generated_images_for_articles([article_id])
    refreshed = article_to_dict(get_article(article_id)) or article_to_dict(article) or {}

    for key in ("generated_poster_image", "image_path"):
        image_path = to_relative_media_path(refreshed.get(key))
        if image_path:
            target = (BASE_DIR / image_path).resolve()
            try:
                target.relative_to(BASE_DIR.resolve())
            except ValueError:
                continue
            if target.exists() and target.is_file():
                refreshed["generated_poster_image"] = image_path
                return target, refreshed

    export_image = resolve_article_export_image(refreshed)
    if export_image:
        relative_path = str(export_image.resolve().relative_to(BASE_DIR.resolve())).replace("\\", "/")
        refreshed["generated_poster_image"] = relative_path
        return export_image, refreshed

    return None, refreshed


def build_facebook_bulk_caption(articles):
    valid_articles = [article for article in articles or [] if article]
    parts = ["📌 TIN MỚI TỪ PNEWS", ""]

    for index, article in enumerate(valid_articles, start=1):
        title = str(article.get("title") or "Cập nhật tin tức mới").strip()
        summary = str(article.get("summary") or "").strip()
        source = str(article.get("source") or "PNews").strip()
        url = str(article.get("url") or "").strip()

        parts.append(f"{index}. {title}")
        if summary:
            parts.append(summary)
        parts.append(f"Nguồn: {source}")
        if url:
            parts.append(f"🔗 Xem chi tiết: {url}")
        parts.append("")

    parts.extend(
        [
            "PNews tự động tổng hợp và chọn lọc các tin tức nổi bật về giáo dục, khoa học, công nghệ và hoạt động PTIT.",
            "",
            "#PNews #PTIT #TinTucCongNghe #GiaoDuc #KhoaHocCongNghe",
        ]
    )
    return "\n".join(parts).strip()


def ensure_generated_images_for_articles(article_ids):
    ids = [int(raw_id) for raw_id in (article_ids or []) if str(raw_id).isdigit()]
    if not ids:
        return 0

    placeholders = ",".join("?" for _ in ids)
    with connect_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM articles WHERE id IN ({placeholders})",
            ids,
        ).fetchall()

    if not rows:
        return 0

    generated_images = find_generated_images()
    output_dir = DATA_DIR / "generated_images" / datetime.now().strftime("%Y-%m-%d")
    timestamp = now_iso()
    updates = []

    for row in rows:
        article = dict(row)
        article_id = int(article["id"])

        existing = to_relative_media_path(article.get("image_path"))
        if existing:
            if existing != (article.get("image_path") or ""):
                updates.append((existing, existing, timestamp, article_id))
            continue

        matched = match_generated_image(article.get("title", ""), generated_images)
        if matched:
            updates.append((matched, matched, timestamp, article_id))
            continue

        try:
            generated_path = generate_news_card(article, str(output_dir))
            relative_path = to_relative_media_path(generated_path)
        except Exception as exc:
            LOGGER.warning("Khong tao duoc anh an pham cho bai #%s: %s", article_id, exc)
            continue

        if relative_path:
            updates.append((relative_path, relative_path, timestamp, article_id))
            generated_images.insert(0, Path(BASE_DIR / relative_path))

    if not updates:
        return 0

    with connect_db() as conn:
        conn.executemany(
            """
            UPDATE articles
            SET
                image_path = ?,
                generated_poster_image = CASE
                    WHEN generated_poster_image IS NULL OR TRIM(generated_poster_image) = '' THEN ?
                    ELSE generated_poster_image
                END,
                updated_at = ?
            WHERE id = ?
            """,
            updates,
        )
        conn.commit()

    return len(updates)


def ensure_generated_images_for_rows(rows, limit=4):
    missing_ids = []
    for row in rows or []:
        image_path = to_relative_media_path(row["image_path"])
        if not image_path and str(row["id"]).isdigit():
            missing_ids.append(int(row["id"]))
    if not missing_ids:
        return 0
    return ensure_generated_images_for_articles(missing_ids[: max(1, int(limit or 1))])


def normalize_text_key(value):
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return " ".join(text.casefold().split())


def resolve_client_topic(value):
    value_key = normalize_text_key(value)
    for topic in CLIENT_TOPIC_ORDER:
        if normalize_text_key(topic) == value_key:
            return topic
    return str(value or "").strip()


def canonical_topic_from_values(source="", category="", content_topic=""):
    source_key = normalize_text_key(source)
    raw = str(category or content_topic or "").strip()
    raw_key = normalize_text_key(raw)

    if "ptit" in source_key or "ptit" in raw_key:
        return "Tin tức PTIT"
    if "giao duc" in raw_key:
        return "Giáo dục"
    if "khoa giao" in raw_key or "khoa hoc" in raw_key or "cong nghe" in raw_key:
        return "Khoa học - Công nghệ"
    if "kinh doanh" in raw_key:
        return "Kinh doanh"
    if "phap luat" in raw_key:
        return "Pháp luật"
    if "suc khoe" in raw_key:
        return "Sức khỏe"
    if "the gioi" in raw_key:
        return "Thế giới"
    if "the thao" in raw_key:
        return "Thể thao"
    if "thoi su" in raw_key:
        return "Thời sự"
    if "giai tri" in raw_key:
        return "Giải trí"
    if "tin tuc chung" in raw_key:
        return "Thời sự"
    return raw or "Tin mới"


def canonical_topic_sql_expr():
    raw = "COALESCE(NULLIF(category, ''), NULLIF(content_topic, ''), '')"
    source = "COALESCE(source, '')"
    return f"""
    CASE
      WHEN {source} LIKE '%PTIT%' OR {raw} LIKE '%PTIT%' THEN 'Tin tức PTIT'
      WHEN {raw} LIKE '%Giáo dục%' OR {raw} LIKE '%giao duc%' THEN 'Giáo dục'
      WHEN {raw} LIKE '%Khoa giáo%' OR {raw} LIKE '%Khoa học%' OR {raw} LIKE '%Công nghệ%' OR {raw} LIKE '%khoa hoc%' OR {raw} LIKE '%cong nghe%' THEN 'Khoa học - Công nghệ'
      WHEN {raw} LIKE '%Kinh doanh%' OR {raw} LIKE '%kinh doanh%' THEN 'Kinh doanh'
      WHEN {raw} LIKE '%Pháp luật%' OR {raw} LIKE '%phap luat%' THEN 'Pháp luật'
      WHEN {raw} LIKE '%Sức khỏe%' OR {raw} LIKE '%suc khoe%' THEN 'Sức khỏe'
      WHEN {raw} LIKE '%Thế giới%' OR {raw} LIKE '%the gioi%' THEN 'Thế giới'
      WHEN {raw} LIKE '%Thể thao%' OR {raw} LIKE '%the thao%' THEN 'Thể thao'
      WHEN {raw} LIKE '%Thời sự%' OR {raw} LIKE '%thoi su%' THEN 'Thời sự'
      WHEN {raw} LIKE '%Giải trí%' OR {raw} LIKE '%giai tri%' THEN 'Giải trí'
      WHEN {raw} LIKE '%Tin tức chung%' OR {raw} LIKE '%tin tuc chung%' THEN 'Thời sự'
      ELSE {raw}
    END
    """


def client_topic_label(article):
    if isinstance(article, sqlite3.Row):
        return canonical_topic_from_values(
            article["source"],
            article["category"],
            article["content_topic"],
        )
    return canonical_topic_from_values(
        article.get("source", ""),
        article.get("category", ""),
        article.get("content_topic", ""),
    )


def admin_date_filter_from_query(query):
    raw_date = (query.get("date") or [None])[0]
    if raw_date is None:
        return today_iso_date()

    value = str(raw_date or "").strip().lower()
    if value in {"all", "any"}:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return min(value, today_iso_date())
    return today_iso_date()


def article_date_sql_expr(status=None):
    if status == "approved":
        return "COALESCE(NULLIF(approved_at, ''), NULLIF(reviewed_at, ''), NULLIF(updated_at, ''), NULLIF(published_at, ''), NULLIF(crawled_at, ''), created_at)"
    if status == "rejected":
        return "COALESCE(NULLIF(reviewed_at, ''), NULLIF(updated_at, ''), NULLIF(published_at, ''), NULLIF(crawled_at, ''), created_at)"
    if status == "deleted":
        return "COALESCE(NULLIF(deleted_at, ''), NULLIF(updated_at, ''), NULLIF(published_at, ''), NULLIF(crawled_at, ''), created_at)"
    return "COALESCE(NULLIF(published_at, ''), NULLIF(crawled_at, ''), created_at)"


def article_filter_where(status=None, q=None, topic=None, source=None, date_filter=None, canonical_topic=False):
    where = []
    params = {}

    if status:
        where.append("status = :status")
        params["status"] = status

    if q:
        where.append("(title LIKE :q OR summary LIKE :q OR source LIKE :q)")
        params["q"] = f"%{q}%"

    if topic:
        if canonical_topic:
            topic = resolve_client_topic(topic)
            if topic == "Tin tức chung":
                where.append(
                    "(lower(COALESCE(source, '')) NOT LIKE '%ptit%' "
                    "AND lower(COALESCE(source, '')) NOT LIKE '%buu chinh%' "
                    "AND lower(COALESCE(source, '')) NOT LIKE '%bưu chính%')"
                )
            else:
                where.append(f"({canonical_topic_sql_expr()} = :topic)")
        else:
            where.append("(content_topic = :topic OR category = :topic)")
        params["topic"] = topic

    if source:
        where.append("source = :source")
        params["source"] = source

    if date_filter:
        where.append(f"date({article_date_sql_expr(status)}) = :date_filter")
        params["date_filter"] = date_filter

    return where, params


def query_articles(status=None, q=None, topic=None, source=None, date_filter=None, limit=None, offset=0, canonical_topic=False):
    where, params = article_filter_where(
        status=status,
        q=q,
        topic=topic,
        source=source,
        date_filter=date_filter,
        canonical_topic=canonical_topic,
    )
    sql = "SELECT * FROM articles"
    if where:
        sql += " WHERE " + " AND ".join(where)
    if status == "approved":
        sql += """
        ORDER BY
          date(COALESCE(NULLIF(approved_at, ''), NULLIF(reviewed_at, ''), NULLIF(updated_at, ''), NULLIF(published_at, ''), NULLIF(crawled_at, ''), created_at)) DESC,
          datetime(COALESCE(NULLIF(approved_at, ''), NULLIF(reviewed_at, ''), NULLIF(updated_at, ''), NULLIF(published_at, ''), NULLIF(crawled_at, ''), created_at)) DESC,
          CASE
            WHEN lower(COALESCE(source, '')) LIKE '%ptit%' THEN 0
            WHEN lower(COALESCE(source, '')) LIKE '%buu chinh%' THEN 0
            WHEN lower(COALESCE(source, '')) LIKE '%bưu chính%' THEN 0
            ELSE 1
          END ASC,
          NULLIF(published_at, '') DESC,
          id DESC
        """
    else:
        sql += """
        ORDER BY
          date(COALESCE(NULLIF(published_at, ''), NULLIF(crawled_at, ''), created_at)) DESC,
          datetime(COALESCE(NULLIF(published_at, ''), NULLIF(crawled_at, ''), created_at)) DESC,
          NULLIF(published_at, '') DESC,
          id DESC
        """
    if limit:
        sql += " LIMIT :limit"
        params["limit"] = limit
        if offset:
            sql += " OFFSET :offset"
            params["offset"] = max(0, int(offset or 0))

    with connect_db() as conn:
        return conn.execute(sql, params).fetchall()


def count_articles(status=None, q=None, topic=None, source=None, date_filter=None, canonical_topic=False):
    where, params = article_filter_where(
        status=status,
        q=q,
        topic=topic,
        source=source,
        date_filter=date_filter,
        canonical_topic=canonical_topic,
    )
    sql = "SELECT COUNT(*) AS total FROM articles"
    if where:
        sql += " WHERE " + " AND ".join(where)

    with connect_db() as conn:
        return conn.execute(sql, params).fetchone()["total"]


def get_article(article_id):
    with connect_db() as conn:
        return conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()


def set_article_status(article_id, status):
    timestamp = now_iso()
    with connect_db() as conn:
        conn.execute(
            """
            UPDATE articles
            SET
                status = :status,
                approval_status = CASE
                    WHEN :status IN ('pending', 'approved', 'rejected') THEN :status
                    ELSE approval_status
                END,
                reviewed_at = CASE
                    WHEN :status IN ('approved', 'rejected') THEN :timestamp
                    ELSE reviewed_at
                END,
                approved_at = CASE
                    WHEN :status = 'approved' THEN :timestamp
                    ELSE approved_at
                END,
                deleted_at = CASE
                    WHEN :status = 'deleted' THEN :timestamp
                    ELSE deleted_at
                END,
                updated_at = :timestamp
            WHERE id = :id
            """,
            {"status": status, "timestamp": timestamp, "id": article_id},
        )
        conn.commit()

    return True


def set_articles_status(article_ids, status):
    ids = [int(article_id) for article_id in article_ids if str(article_id).isdigit()]
    if not ids:
        return 0

    timestamp = now_iso()
    params = {
        "status": status,
        "timestamp": timestamp,
    }
    id_placeholders = []
    for index, article_id in enumerate(ids):
        key = f"id_{index}"
        id_placeholders.append(f":{key}")
        params[key] = article_id
    placeholders = ",".join(id_placeholders)

    with connect_db() as conn:
        cursor = conn.execute(
            f"""
            UPDATE articles
            SET
                status = :status,
                approval_status = CASE
                    WHEN :status IN ('pending', 'approved', 'rejected') THEN :status
                    ELSE approval_status
                END,
                reviewed_at = CASE
                    WHEN :status IN ('approved', 'rejected') THEN :timestamp
                    ELSE reviewed_at
                END,
                approved_at = CASE
                    WHEN :status = 'approved' THEN :timestamp
                    ELSE approved_at
                END,
                deleted_at = CASE
                    WHEN :status = 'deleted' THEN :timestamp
                    ELSE deleted_at
                END,
                updated_at = :timestamp
            WHERE id IN ({placeholders})
            """,
            params,
        )
        conn.commit()
        rowcount = cursor.rowcount

    return rowcount


def article_to_dict(article):
    return dict(article) if article else None


def update_article_facebook_fields(article_id, **fields):
    allowed = {
        "facebook_posted",
        "facebook_post_id",
        "facebook_permalink",
        "facebook_published_at",
        "facebook_publish_status",
        "facebook_publish_error",
        "facebook_caption",
        "generated_poster_image",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return

    updates["updated_at"] = now_iso()
    assignments = ", ".join(f"{key} = :{key}" for key in updates)
    updates["id"] = int(article_id)
    with connect_db() as conn:
        conn.execute(
            f"UPDATE articles SET {assignments} WHERE id = :id",
            updates,
        )
        conn.commit()


def clear_article_facebook_fields(article_ids):
    ids = [int(article_id) for article_id in (article_ids or []) if str(article_id).isdigit()]
    if not ids:
        return 0

    placeholders = ",".join("?" for _ in ids)
    timestamp = now_iso()
    with connect_db() as conn:
        cursor = conn.execute(
            f"""
            UPDATE articles
            SET
                facebook_posted = 0,
                facebook_post_id = '',
                facebook_permalink = '',
                facebook_published_at = '',
                facebook_publish_status = 'not_posted',
                facebook_publish_error = '',
                updated_at = ?
            WHERE id IN ({placeholders})
            """,
            [timestamp, *ids],
        )
        conn.commit()
        return cursor.rowcount


def article_is_approved_for_facebook(article):
    if not article:
        return False
    status = str(article.get("status") or "").strip()
    return status == "approved"


def article_facebook_status(article):
    raw_status = str(article.get("facebook_publish_status") or "").strip()
    if int(article.get("facebook_posted") or 0) and raw_status in {"", "not_posted"}:
        return "success"
    if raw_status:
        return raw_status
    return "success" if int(article.get("facebook_posted") or 0) else "not_posted"


def article_facebook_result_data(article, caption=""):
    return {
        "article_id": int(article.get("id")),
        "facebook_post_id": article.get("facebook_post_id") or "",
        "facebook_permalink": article.get("facebook_permalink") or "",
        "facebook_caption": caption or article.get("facebook_caption") or "",
    }


def publish_article_to_facebook(article_id):
    if not str(article_id).isdigit():
        return {
            "success": False,
            "message": "Article không hợp lệ.",
            "error": "article_id phải là số.",
        }, HTTPStatus.BAD_REQUEST

    article = article_to_dict(get_article(int(article_id)))
    if not article:
        return {
            "success": False,
            "message": "Không tìm thấy bài viết.",
            "error": "Article không tồn tại.",
        }, HTTPStatus.NOT_FOUND

    if not article_is_approved_for_facebook(article):
        return {
            "success": False,
            "message": "Chỉ bài đã duyệt mới được đăng Facebook.",
            "error": "Bài viết chưa được duyệt.",
            "data": {"article_id": int(article["id"])},
        }, HTTPStatus.BAD_REQUEST

    if int(article.get("facebook_posted") or 0):
        return {
            "success": False,
            "message": "Bài viết đã được đăng Facebook.",
            "error": "Bài viết đã được đăng Facebook.",
            "data": article_facebook_result_data(article),
        }, HTTPStatus.CONFLICT

    poster_path, article = resolve_article_facebook_image(article)
    if not poster_path:
        return {
            "success": False,
            "message": "Không tìm thấy ảnh ấn phẩm để đăng Facebook.",
            "error": "Không tạo được ảnh ấn phẩm cho bài viết.",
            "data": {"article_id": int(article["id"])},
        }, HTTPStatus.BAD_GATEWAY

    caption = buildFacebookCaption(article)
    poster_image = str(article.get("generated_poster_image") or "").strip()
    article["facebook_caption"] = caption

    LOGGER.info("Bat dau dang Facebook article_id=%s", article["id"])
    LOGGER.info("Article ID=%s caption_da_tao=%s", article["id"], caption)
    update_article_facebook_fields(
        article["id"],
        facebook_caption=caption,
        facebook_publish_status="posting",
        facebook_publish_error="",
        generated_poster_image=poster_image,
    )

    try:
        response = publishPhotoPost(caption, poster_path)
        photo_id = str(response.get("id") or "").strip()
        post_id = str(response.get("post_id") or photo_id).strip()
        if not post_id:
            raise FacebookPublishError("Facebook API khong tra ve post_id.")

        permalink = ""
        post_info_error = ""
        try:
            post_info = getPostInfo(post_id)
            permalink = str(post_info.get("permalink_url") or "").strip()
            LOGGER.info("Permalink URL article_id=%s url=%s", article["id"], permalink)
        except FacebookPublishError as exc:
            post_info_error = f"Da dang thanh cong nhung chua lay duoc permalink: {exc}"
            LOGGER.warning(post_info_error)

        published_at = now_iso()
        update_article_facebook_fields(
            article["id"],
            facebook_posted=1,
            facebook_post_id=post_id,
            facebook_permalink=permalink,
            facebook_published_at=published_at,
            facebook_publish_status="success",
            facebook_publish_error=post_info_error,
            facebook_caption=caption,
        )
        LOGGER.info(
            "Dang Facebook thanh cong article_id=%s post_id=%s permalink=%s",
            article["id"],
            post_id,
            permalink,
        )
        return {
            "success": True,
            "message": "Đăng Facebook thành công.",
            "data": {
                "article_id": int(article["id"]),
                "facebook_post_id": post_id,
                "facebook_photo_id": photo_id,
                "facebook_permalink": permalink,
                "facebook_caption": caption,
            },
        }, HTTPStatus.OK
    except (FacebookConfigError, FacebookAPIError, FacebookPublishError) as exc:
        safe_error = str(exc)[:1000]
        LOGGER.error("Dang Facebook that bai article_id=%s error=%s", article["id"], safe_error)
    except Exception as exc:
        safe_error = str(exc)[:1000]
        LOGGER.exception("Dang Facebook loi khong mong doi article_id=%s", article["id"])

    update_article_facebook_fields(
        article["id"],
        facebook_publish_status="failed",
        facebook_publish_error=safe_error,
        facebook_caption=caption,
    )
    return {
        "success": False,
        "message": "Đăng Facebook thất bại.",
        "error": safe_error,
        "data": {"article_id": int(article["id"]), "facebook_caption": caption},
    }, HTTPStatus.BAD_GATEWAY


def publish_articles_to_facebook_bulk(article_ids, delay_seconds=1.2):
    clean_ids = []
    seen_ids = set()
    for raw_id in article_ids or []:
        if str(raw_id).isdigit():
            article_id = int(raw_id)
            if article_id not in seen_ids:
                clean_ids.append(article_id)
                seen_ids.add(article_id)

    if not clean_ids:
        return {
            "success": False,
            "message": "Chưa chọn bài viết nào.",
            "post_count": 0,
            "results": [],
        }

    if len(clean_ids) == 1:
        article_id = clean_ids[0]
        result, status_code = publish_article_to_facebook(article_id)
        data = result.get("data") or {}
        if result.get("success"):
            status = "success"
            item = {
                "article_id": article_id,
                "status": status,
                "facebook_post_id": data.get("facebook_post_id", ""),
                "facebook_permalink": data.get("facebook_permalink", ""),
            }
        elif status_code in {HTTPStatus.BAD_REQUEST, HTTPStatus.CONFLICT}:
            item = {
                "article_id": article_id,
                "status": "skipped",
                "reason": result.get("message") or result.get("error") or "Bỏ qua bài viết.",
            }
        else:
            item = {
                "article_id": article_id,
                "status": "failed",
                "error": result.get("error") or result.get("message") or "Đăng Facebook thất bại.",
            }
        return {
            "success": result.get("success", False),
            "message": result.get("message") or "Hoàn tất xử lý đăng Facebook.",
            "post_count": 1 if result.get("success") else 0,
            "results": [item],
        }

    placeholders = ",".join("?" for _ in clean_ids)
    with connect_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM articles WHERE id IN ({placeholders})",
            clean_ids,
        ).fetchall()
    articles_by_id = {int(row["id"]): article_to_dict(row) for row in rows}

    results = []
    publish_articles = []
    image_paths = []

    for article_id in clean_ids:
        article = articles_by_id.get(article_id)
        if not article:
            results.append(
                {
                    "article_id": article_id,
                    "status": "skipped",
                    "reason": "Không tìm thấy bài viết.",
                }
            )
            continue
        if not article_is_approved_for_facebook(article):
            results.append(
                {
                    "article_id": article_id,
                    "status": "skipped",
                    "reason": "Chỉ bài đã duyệt mới được đăng Facebook.",
                }
            )
            continue
        if int(article.get("facebook_posted") or 0):
            results.append(
                {
                    "article_id": article_id,
                    "status": "skipped",
                    "reason": "Bài viết đã được đăng Facebook.",
                    "facebook_post_id": article.get("facebook_post_id") or "",
                    "facebook_permalink": article.get("facebook_permalink") or "",
                }
            )
            continue

        image_path, refreshed = resolve_article_facebook_image(article)
        if not image_path:
            results.append(
                {
                    "article_id": article_id,
                    "status": "failed",
                    "error": "Không tạo được ảnh ấn phẩm cho bài viết.",
                }
            )
            continue
        publish_articles.append(refreshed)
        image_paths.append(image_path)

    if not publish_articles:
        return {
            "success": False,
            "message": "Không có bài hợp lệ để đăng Facebook.",
            "post_count": 0,
            "results": results,
        }

    if len(publish_articles) == 1:
        result, status_code = publish_article_to_facebook(publish_articles[0]["id"])
        data = result.get("data") or {}
        item = {
            "article_id": int(publish_articles[0]["id"]),
            "status": "success" if result.get("success") else "failed",
            "facebook_post_id": data.get("facebook_post_id", ""),
            "facebook_permalink": data.get("facebook_permalink", ""),
        }
        if not result.get("success"):
            item["error"] = result.get("error") or result.get("message") or "Đăng Facebook thất bại."
        results.append(item)
        return {
            "success": result.get("success", False),
            "message": result.get("message") or "Hoàn tất xử lý đăng Facebook.",
            "post_count": 1 if result.get("success") else 0,
            "results": results,
        }

    caption = build_facebook_bulk_caption(publish_articles)
    for article in publish_articles:
        update_article_facebook_fields(
            article["id"],
            facebook_caption=caption,
            facebook_publish_status="posting",
            facebook_publish_error="",
        )

    try:
        response = publishMultiPhotoPost(caption, image_paths)
        photo_id = str(response.get("id") or "").strip()
        post_id = str(response.get("post_id") or photo_id).strip()
        if not post_id:
            raise FacebookPublishError("Facebook API khong tra ve post_id.")

        permalink = ""
        post_info_error = ""
        try:
            post_info = getPostInfo(post_id)
            permalink = str(post_info.get("permalink_url") or "").strip()
        except FacebookPublishError as exc:
            post_info_error = f"Da dang thanh cong nhung chua lay duoc permalink: {exc}"
            LOGGER.warning(post_info_error)

        published_at = now_iso()
        for article in publish_articles:
            update_article_facebook_fields(
                article["id"],
                facebook_posted=1,
                facebook_post_id=post_id,
                facebook_permalink=permalink,
                facebook_published_at=published_at,
                facebook_publish_status="success",
                facebook_publish_error=post_info_error,
                facebook_caption=caption,
            )
            results.append(
                {
                    "article_id": int(article["id"]),
                    "status": "success",
                    "facebook_post_id": post_id,
                    "facebook_photo_id": photo_id,
                    "facebook_permalink": permalink,
                }
            )
        return {
            "success": True,
            "message": f"Đã đăng 1 bài Facebook gồm {len(publish_articles)} ảnh ấn phẩm.",
            "post_count": 1,
            "facebook_post_id": post_id,
            "facebook_photo_id": photo_id,
            "facebook_permalink": permalink,
            "results": results,
        }
    except (FacebookConfigError, FacebookAPIError, FacebookPublishError) as exc:
        safe_error = str(exc)[:1000]
        LOGGER.error("Dang Facebook bulk that bai ids=%s error=%s", clean_ids, safe_error)
    except Exception as exc:
        safe_error = str(exc)[:1000]
        LOGGER.exception("Dang Facebook bulk loi khong mong doi ids=%s", clean_ids)

    for article in publish_articles:
        update_article_facebook_fields(
            article["id"],
            facebook_publish_status="failed",
            facebook_publish_error=safe_error,
            facebook_caption=caption,
        )
        results.append(
            {
                "article_id": int(article["id"]),
                "status": "failed",
                "error": safe_error,
            }
        )

    return {
        "success": False,
        "message": "Đăng Facebook thất bại.",
        "post_count": 0,
        "results": results,
    }


def summarize_facebook_bulk_result(result):
    results = result.get("results") or []
    sent = sum(1 for item in results if item.get("status") == "success")
    skipped = sum(1 for item in results if item.get("status") == "skipped")
    failed = sum(1 for item in results if item.get("status") == "failed")
    if result.get("post_count") == 1 and sent > 1:
        return f"Facebook: Đã đăng bài viết cho {sent} bài đã chọn, bỏ qua {skipped}, lỗi {failed}."
    return f"Facebook: Đã đăng bài viết cho {sent} bài đã chọn, bỏ qua {skipped}, lỗi {failed}."


def create_uploaded_article(fields, file_part):
    title = fields.get("title", "").strip()
    if not title:
        raise ValueError("Cần nhập tiêu đề ấn phẩm.")

    image_path = ""
    if file_part and file_part.get("content"):
        image_path = save_uploaded_file(file_part, title)

    status = "approved" if fields.get("publish_now") == "on" else "pending"
    timestamp = now_iso()

    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO articles (
                source, title, url, crawled_at, published_at, thumbnail, summary,
                newspaper_type, content_topic, category, image_path,
                generated_poster_image, approval_status, status,
                created_at, updated_at, approved_at, reviewed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fields.get("source", "Admin upload").strip() or "Admin upload",
                title,
                fields.get("url", "").strip(),
                timestamp,
                timestamp,
                "",
                fields.get("summary", "").strip(),
                fields.get("newspaper_type", "").strip(),
                fields.get("content_topic", "").strip(),
                fields.get("category", "").strip(),
                image_path,
                image_path,
                status,
                status,
                timestamp,
                timestamp,
                timestamp if status == "approved" else "",
                timestamp if status == "approved" else "",
            ),
        )
        article_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.commit()
    return article_id, status


def save_uploaded_file(file_part, title):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    raw_name = file_part.get("filename") or "upload.jpg"
    extension = Path(raw_name).suffix.lower()
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        raise ValueError("Chỉ hỗ trợ ảnh JPG, PNG, WEBP hoặc GIF.")

    digest = hashlib.sha256(file_part["content"]).hexdigest()[:12]
    filename = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{slugify(title)}-{digest}{extension}"
    output_path = UPLOAD_DIR / filename
    output_path.write_bytes(file_part["content"])
    return str(output_path.relative_to(BASE_DIR)).replace("\\", "/")


def get_topics(status="approved"):
    params = {}
    status_clause = ""
    if status:
        status_clause = "status = :status AND "
        params["status"] = status

    with connect_db() as conn:
        rows = conn.execute(
            f"""
            SELECT content_topic AS value FROM articles
            WHERE {status_clause}content_topic != ''
            UNION
            SELECT category AS value FROM articles
            WHERE {status_clause}category != ''
            ORDER BY value
            """,
            params,
        ).fetchall()
    return [row["value"] for row in rows]


def get_client_topics(status="approved"):
    params = {}
    where = []
    if status:
        where.append("status = :status")
        params["status"] = status
    where_sql = " WHERE " + " AND ".join(where) if where else ""

    with connect_db() as conn:
        rows = conn.execute(
            f"SELECT source, category, content_topic FROM articles{where_sql}",
            params,
        ).fetchall()

    topics = {
        canonical_topic_from_values(row["source"], row["category"], row["content_topic"])
        for row in rows
    }
    if any("ptit" not in normalize_text_key(row["source"]) for row in rows):
        topics.add("Tin tức chung")
    ordered = [topic for topic in CLIENT_TOPIC_ORDER if topic in topics]
    ordered.extend(sorted(topic for topic in topics if topic not in CLIENT_TOPIC_ORDER))
    return ordered


def get_sources(status=None):
    params = {}
    status_clause = ""
    if status:
        status_clause = "status = :status AND "
        params["status"] = status

    with connect_db() as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT source AS value
            FROM articles
            WHERE {status_clause}source != ''
            ORDER BY value
            """,
            params,
        ).fetchall()
    return [row["value"] for row in rows]


def get_counts():
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS total FROM articles GROUP BY status"
        ).fetchall()
    counts = {status: 0 for status in STATUS_LABELS}
    for row in rows:
        counts[row["status"]] = row["total"]
    return counts


def table_exists(conn, table_name):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def get_table_columns(conn, table_name):
    if not table_exists(conn, table_name):
        return set()
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")}


def normalize_status_group(status):
    value = str(status or "").strip().lower()
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[\s_-]+", " ", value)
    if value in {"approved", "published", "publish", "public", "posted", "dang", "da dang", "duyet", "da duyet"}:
        return "published"
    if value in {"pending", "waiting", "draft", "review", "cho duyet", "can duyet", "moi"}:
        return "pending"
    if value in {"rejected", "reject", "hidden", "unpublished", "tu choi", "bi tu choi", "go khoi client"}:
        return "rejected"
    if value in {"deleted", "delete", "removed", "archived", "xoa", "da xoa"}:
        return "deleted"
    return "other"


def sql_blank_condition(column_name):
    return f"({column_name} IS NULL OR TRIM({column_name}) = '')"


def sql_value_expr(columns, column_name, fallback="''"):
    if column_name in columns:
        return column_name
    return fallback


def safe_count(conn, where_sql="", params=None):
    sql = "SELECT COUNT(*) AS total FROM articles"
    if where_sql:
        sql += f" WHERE {where_sql}"
    return conn.execute(sql, params or {}).fetchone()["total"]


def get_article_status_counts(conn, columns):
    grouped = {"published": 0, "pending": 0, "rejected": 0, "deleted": 0, "other": 0}
    raw = []
    if "status" not in columns:
        grouped["published"] = safe_count(conn)
        return grouped, raw

    rows = conn.execute(
        """
        SELECT COALESCE(NULLIF(TRIM(status), ''), 'unknown') AS status, COUNT(*) AS total
        FROM articles
        GROUP BY COALESCE(NULLIF(TRIM(status), ''), 'unknown')
        ORDER BY total DESC
        """
    ).fetchall()
    for row in rows:
        status = row["status"]
        total = row["total"]
        grouped[normalize_status_group(status)] += total
        raw.append({"status": status, "total": total})
    return grouped, raw


def get_source_counts(conn, columns):
    if "source" not in columns:
        return []
    rows = conn.execute(
        """
        SELECT COALESCE(NULLIF(TRIM(source), ''), 'Không rõ') AS label, COUNT(*) AS total
        FROM articles
        GROUP BY COALESCE(NULLIF(TRIM(source), ''), 'Không rõ')
        ORDER BY total DESC, label ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def get_topic_counts(conn, columns, limit=10):
    if "content_topic" in columns and "category" in columns:
        topic_expr = "COALESCE(NULLIF(TRIM(content_topic), ''), NULLIF(TRIM(category), ''), 'Chưa phân loại')"
    elif "content_topic" in columns:
        topic_expr = "COALESCE(NULLIF(TRIM(content_topic), ''), 'Chưa phân loại')"
    elif "category" in columns:
        topic_expr = "COALESCE(NULLIF(TRIM(category), ''), 'Chưa phân loại')"
    else:
        return []

    rows = conn.execute(
        f"""
        SELECT {topic_expr} AS label, COUNT(*) AS total
        FROM articles
        GROUP BY {topic_expr}
        ORDER BY total DESC, label ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_recent_articles(conn, columns, limit=10):
    id_expr = sql_value_expr(columns, "id", "rowid")
    title_expr = sql_value_expr(columns, "title", "'Không có tiêu đề'")
    source_expr = sql_value_expr(columns, "source")
    status_expr = sql_value_expr(columns, "status")
    url_expr = sql_value_expr(columns, "url")
    crawled_expr = sql_value_expr(columns, "crawled_at")
    published_expr = sql_value_expr(columns, "published_at")
    topic_expr = (
        "COALESCE(NULLIF(TRIM(content_topic), ''), NULLIF(TRIM(category), ''), '')"
        if {"content_topic", "category"}.issubset(columns)
        else sql_value_expr(columns, "content_topic", sql_value_expr(columns, "category"))
    )
    order_parts = []
    if "published_at" in columns:
        order_parts.append("datetime(NULLIF(published_at, '')) DESC")
        order_parts.append("NULLIF(published_at, '') DESC")
    if "crawled_at" in columns:
        order_parts.append("datetime(NULLIF(crawled_at, '')) DESC")
        order_parts.append("NULLIF(crawled_at, '') DESC")
    if "created_at" in columns:
        order_parts.append("datetime(NULLIF(created_at, '')) DESC")
    order_parts.append(f"{id_expr} DESC")
    order_sql = ", ".join(order_parts)

    rows = conn.execute(
        f"""
        SELECT
            {id_expr} AS id,
            {title_expr} AS title,
            {source_expr} AS source,
            {topic_expr} AS topic,
            {status_expr} AS status,
            {crawled_expr} AS crawled_at,
            {published_expr} AS published_at,
            {url_expr} AS url
        FROM articles
        ORDER BY {order_sql}
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_data_quality_warnings(conn, columns, source_counts):
    warnings = []
    missing_summary = 0
    missing_thumbnail = 0
    missing_url = 0
    duplicate_url_groups = 0

    if "summary" in columns:
        missing_summary = safe_count(conn, sql_blank_condition("summary"))
        if missing_summary:
            warnings.append({
                "label": "Bài thiếu summary",
                "value": missing_summary,
                "detail": "Nên bổ sung tóm tắt trước khi duyệt để client hiển thị đẹp hơn.",
                "level": "warning",
            })

    if "thumbnail" in columns or "image_path" in columns:
        image_checks = []
        if "thumbnail" in columns:
            image_checks.append(sql_blank_condition("thumbnail"))
        if "image_path" in columns:
            image_checks.append(sql_blank_condition("image_path"))
        missing_thumbnail = safe_count(conn, " AND ".join(image_checks))
        if missing_thumbnail:
            warnings.append({
                "label": "Bài thiếu thumbnail",
                "value": missing_thumbnail,
                "detail": "Các bài này sẽ cần ảnh fallback hoặc ảnh upload thủ công.",
                "level": "warning",
            })

    if "url" in columns:
        missing_url = safe_count(conn, sql_blank_condition("url"))
        if missing_url:
            warnings.append({
                "label": "Bài không có URL",
                "value": missing_url,
                "detail": "Thiếu link gốc làm giảm khả năng kiểm chứng nguồn tin.",
                "level": "danger",
            })
        duplicate_url_groups = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM (
                SELECT url
                FROM articles
                WHERE url IS NOT NULL AND TRIM(url) != ''
                GROUP BY url
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()["total"]
        if duplicate_url_groups:
            warnings.append({
                "label": "URL bị trùng",
                "value": duplicate_url_groups,
                "detail": "Có nhóm bài đang dùng cùng một URL nguồn.",
                "level": "danger",
            })

    stale_sources = []
    today = datetime.now().strftime("%Y-%m-%d")
    if "crawled_at" in columns and "source" in columns:
        rows = conn.execute(
            """
            SELECT
                COALESCE(NULLIF(TRIM(source), ''), 'Không rõ') AS source,
                MAX(crawled_at) AS latest
            FROM articles
            GROUP BY COALESCE(NULLIF(TRIM(source), ''), 'Không rõ')
            """
        ).fetchall()
        stale_sources = [
            row["source"]
            for row in rows
            if row["latest"] and not str(row["latest"]).startswith(today)
        ]
        if stale_sources:
            warnings.append({
                "label": "Nguồn chưa có bài mới hôm nay",
                "value": len(stale_sources),
                "detail": ", ".join(stale_sources[:4]) + ("..." if len(stale_sources) > 4 else ""),
                "level": "info",
            })

    return {
        "items": warnings,
        "missing_summary": missing_summary,
        "missing_thumbnail": missing_thumbnail,
        "missing_url": missing_url,
        "duplicate_url_groups": duplicate_url_groups,
        "stale_sources": stale_sources,
    }


def get_facebook_dashboard_counts(conn, columns):
    counts = {
        "posted": 0,
        "approved_not_posted": 0,
        "failed": 0,
        "posting": 0,
    }
    if "facebook_posted" not in columns and "facebook_publish_status" not in columns:
        return counts

    facebook_posted_expr = (
        "COALESCE(facebook_posted, 0)"
        if "facebook_posted" in columns
        else "CASE WHEN facebook_publish_status = 'success' THEN 1 ELSE 0 END"
    )
    facebook_status_expr = (
        "COALESCE(NULLIF(TRIM(facebook_publish_status), ''), 'not_posted')"
        if "facebook_publish_status" in columns
        else "CASE WHEN COALESCE(facebook_posted, 0) = 1 THEN 'success' ELSE 'not_posted' END"
    )
    status_filter = "status = 'approved'" if "status" in columns else "1 = 1"

    row = conn.execute(
        f"""
        SELECT
            SUM(CASE WHEN {facebook_posted_expr} = 1 OR {facebook_status_expr} = 'success' THEN 1 ELSE 0 END) AS posted,
            SUM(CASE WHEN {status_filter} AND {facebook_posted_expr} != 1 AND {facebook_status_expr} NOT IN ('success', 'posting') THEN 1 ELSE 0 END) AS approved_not_posted,
            SUM(CASE WHEN {facebook_status_expr} = 'failed' THEN 1 ELSE 0 END) AS failed,
            SUM(CASE WHEN {facebook_status_expr} = 'posting' THEN 1 ELSE 0 END) AS posting
        FROM articles
        """
    ).fetchone()
    if not row:
        return counts

    for key in counts:
        counts[key] = int(row[key] or 0)
    return counts


def get_admin_dashboard_stats():
    stats = {
        "db_path": str(DB_PATH),
        "ready": False,
        "error": "",
        "cards": [],
        "status_counts": {"published": 0, "pending": 0, "rejected": 0, "deleted": 0, "other": 0},
        "raw_status_counts": [],
        "source_counts": [],
        "topic_counts": [],
        "recent_articles": [],
        "warnings": {"items": []},
        "facebook_counts": {
            "posted": 0,
            "approved_not_posted": 0,
            "failed": 0,
            "posting": 0,
        },
        "latest_crawled_at": "",
        "columns": set(),
    }

    if not DB_PATH.exists():
        stats["error"] = "Chưa tìm thấy database CMS."
        return stats

    try:
        with connect_db() as conn:
            if not table_exists(conn, "articles"):
                stats["error"] = "Database hiện chưa có bảng articles."
                return stats

            columns = get_table_columns(conn, "articles")
            stats["columns"] = columns
            total = safe_count(conn)
            status_counts, raw_status_counts = get_article_status_counts(conn, columns)
            source_counts = get_source_counts(conn, columns)
            topic_counts = get_topic_counts(conn, columns)
            recent_articles = get_recent_articles(conn, columns)
            facebook_counts = get_facebook_dashboard_counts(conn, columns)
            latest_crawled_at = ""
            if "published_at" in columns:
                row = conn.execute(
                    "SELECT MAX(NULLIF(published_at, '')) AS latest FROM articles"
                ).fetchone()
                latest_crawled_at = row["latest"] or ""
            if not latest_crawled_at and "crawled_at" in columns:
                row = conn.execute(
                    "SELECT MAX(NULLIF(crawled_at, '')) AS latest FROM articles"
                ).fetchone()
                latest_crawled_at = row["latest"] or ""
            warnings = get_data_quality_warnings(conn, columns, source_counts)

            cards = [
                {"label": "Tổng số bài viết", "value": total, "tone": "blue", "group": "overview"},
                {"label": "Đã đăng / approved", "value": status_counts["published"], "tone": "green", "group": "overview"},
                {"label": "Chờ duyệt / pending", "value": status_counts["pending"], "tone": "amber", "group": "overview"},
                {"label": "Bị từ chối / rejected", "value": status_counts["rejected"], "tone": "red", "group": "overview"},
            ]
            if "status" in columns:
                cards.append({"label": "Đã xóa / deleted", "value": status_counts["deleted"], "tone": "muted", "group": "overview"})
            cards.extend([
                {"label": "Đã đăng Facebook", "value": facebook_counts["posted"], "tone": "facebook", "group": "facebook"},
                {"label": "Đã duyệt chưa đăng FB", "value": facebook_counts["approved_not_posted"], "tone": "blue", "group": "facebook"},
                {"label": "Lỗi đăng Facebook", "value": facebook_counts["failed"], "tone": "red", "group": "facebook"},
                {"label": "Đang đăng Facebook", "value": facebook_counts["posting"], "tone": "amber", "group": "facebook"},
                {"label": "Thiếu summary", "value": warnings["missing_summary"], "tone": "amber", "group": "quality"},
                {"label": "Thiếu thumbnail", "value": warnings["missing_thumbnail"], "tone": "amber", "group": "quality"},
                {"label": "Nguồn báo có dữ liệu", "value": len(source_counts), "tone": "blue", "group": "quality"},
                {"label": "Ngày đăng mới nhất", "value": latest_crawled_at or "Chưa có", "tone": "muted", "wide": True, "group": "quality"},
            ])

            stats.update({
                "ready": True,
                "cards": cards,
                "status_counts": status_counts,
                "raw_status_counts": raw_status_counts,
                "source_counts": source_counts,
                "topic_counts": topic_counts,
                "recent_articles": recent_articles,
                "warnings": warnings,
                "facebook_counts": facebook_counts,
                "latest_crawled_at": latest_crawled_at,
            })
    except sqlite3.Error as exc:
        stats["error"] = f"Không đọc được dữ liệu dashboard: {exc}"
    return stats


def make_media_url(path_or_url):
    value = str(path_or_url or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return value
    safe_value = value.replace("\\", "/")
    return f"/media/{quote(safe_value, safe='/')}"


def article_image_url(article):
    if isinstance(article, sqlite3.Row):
        title = article["title"] or ""
        generated_poster_image = article["generated_poster_image"] or ""
        image_path = article["image_path"] or ""
        thumbnail = article["thumbnail"] or ""
    else:
        title = article.get("title", "")
        generated_poster_image = article.get("generated_poster_image", "")
        image_path = article.get("image_path", "")
        thumbnail = article.get("thumbnail", "")

    local_image = to_relative_media_path(generated_poster_image) or to_relative_media_path(image_path)
    rendered = find_rendered_image(title)
    fallback = DEFAULT_THUMBNAIL if (BASE_DIR / DEFAULT_THUMBNAIL).exists() else ""
    return make_media_url(local_image or rendered or thumbnail or fallback)


def article_target_url(article):
    url = str(article["url"] or "").strip()
    return url or f"/client/article/{article['id']}"


def article_link_attrs(article):
    url = article_target_url(article)
    external = url.startswith(("http://", "https://"))
    attrs = f'href="{escape(url)}"'
    if external:
        attrs += ' target="_blank" rel="noopener"'
    return attrs


def article_click_attrs(article):
    url = article_target_url(article)
    external = "1" if url.startswith(("http://", "https://")) else "0"
    return f'data-article-url="{escape(url)}" data-article-external="{external}" tabindex="0"'


def article_display_summary(article, context="client"):
    summary = str(article["summary"] or "").strip()
    if summary:
        return summary

    source = str(article["source"] or "PNews").strip()
    topic = str(article["category"] or article["content_topic"] or "Tin tức").strip()
    title = str(article["title"] or "bài viết này").strip()

    if context == "admin":
        return f"Bài này chưa có tóm tắt crawl sẵn. Hệ thống sẽ cố gắng bù tóm tắt từ bài gốc khi tạo ảnh ấn phẩm: {title}."

    return f"Cập nhật từ {source} thuộc chuyên mục {topic}: {title}."


def render_select_options(items, selected_value, empty_label):
    options = [f'<option value="">{escape(empty_label)}</option>']
    for item in items:
        selected = "selected" if item == selected_value else ""
        options.append(f'<option value="{escape(item)}" {selected}>{escape(item)}</option>')
    return "".join(options)


def render_date_filter_controls(date_filter, today_link, all_dates_link):
    today = today_iso_date()
    return f"""
      <input type="date" name="date" value="{escape(date_filter)}" max="{escape(today)}" aria-label="Lọc theo ngày">
      <div class="date-filter-actions">
        <a class="button ghost compact {'active' if date_filter == today else ''}" href="{today_link}">Hôm nay</a>
        <a class="button ghost compact {'active' if not date_filter else ''}" href="{all_dates_link}">Tất cả ngày</a>
      </div>
    """


def parse_page(query):
    raw_page = (query.get("page") or ["1"])[0]
    try:
        return max(1, int(raw_page))
    except (TypeError, ValueError):
        return 1


def render_pagination(base_path, page, total, per_page, params=None):
    params = dict(params or {})
    total_pages = max(1, (int(total or 0) + per_page - 1) // per_page)

    if total_pages <= 1:
        return ""

    page = min(max(1, int(page or 1)), total_pages)
    start = max(1, page - 2)
    end = min(total_pages, page + 2)

    if end - start < 4:
        start = max(1, min(start, end - 4))
        end = min(total_pages, max(end, start + 4))

    links = []

    if page > 1:
        links.append(pagination_link(base_path, page - 1, params, "Trước"))

    for page_number in range(start, end + 1):
        links.append(
            pagination_link(
                base_path,
                page_number,
                params,
                str(page_number),
                active=page_number == page,
            )
        )

    if page < total_pages:
        links.append(pagination_link(base_path, page + 1, params, "Sau"))

    return f"""
    <nav class="pagination" aria-label="Phân trang">
      <span>Trang {page}/{total_pages} · {int(total or 0)} bài</span>
      <div>{''.join(links)}</div>
    </nav>
    """


def pagination_link(base_path, page, params, label, active=False):
    query_parts = []
    for key, value in params.items():
        if value:
            query_parts.append(f"{quote(str(key))}={quote(str(value))}")
    query_parts.append(f"page={page}")
    href = f"{base_path}?{'&'.join(query_parts)}"
    return f'<a class="page-link {"active" if active else ""}" href="{href}">{escape(label)}</a>'


def render_client_page(title, body, extra_class=""):
    return f"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} - PNews</title>
  <link rel="stylesheet" href="/assets/styles.css?v={ASSET_VERSION}">
  <script src="/assets/app.js?v={ASSET_VERSION}" defer></script>
</head>
<body class="client-app {escape(extra_class)}">
  <header class="client-topbar">
    <a class="brand brand-logo-link" href="/client" aria-label="PNews">
      <img class="site-logo client-logo" src="{SITE_LOGO_URL}" alt="PNews">
    </a>
    <a class="button ghost compact" href="/admin">Khu vực quản trị</a>
  </header>
  <main class="client-shell">
    {body}
  </main>
  {render_chat_widget()}
  {render_scroll_top_button()}
</body>
</html>"""


def render_admin_head_actions(active_nav="articles"):
    actions = [
        ("dashboard", "Xem tổng quan", "/admin/dashboard", "ghost", False),
        ("articles", "Duyệt bài", "/admin", "primary", False),
        ("upload", "Tải ấn phẩm", "/admin/upload", "primary", False),
        ("client", "Xem client", "/client", "ghost", True),
    ]
    buttons = []
    for key, label, href, variant, external in actions:
        if key == active_nav:
            continue
        attrs = ' target="_blank" rel="noopener"' if external else ""
        buttons.append(f'<a class="button {variant}" href="{href}"{attrs}>{escape(label)}</a>')
    return '<div class="admin-actions">' + "".join(buttons) + "</div>"


def render_admin_page(title, body, extra_class="", active_nav="articles"):
    dashboard_active = "active" if active_nav == "dashboard" else ""
    articles_active = "active" if active_nav == "articles" else ""
    upload_active = "active" if active_nav == "upload" else ""
    return f"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} - Quản trị PNews</title>
  <link rel="stylesheet" href="/assets/styles.css?v={ASSET_VERSION}">
  <script src="/assets/app.js?v={ASSET_VERSION}" defer></script>
</head>
<body class="admin-app {escape(extra_class)}">
  <aside class="admin-sidebar">
    <a class="brand admin-brand brand-logo-link" href="/admin" aria-label="PNews Admin">
      <img class="site-logo admin-logo" src="{SITE_LOGO_URL}" alt="PNews">
    </a>
    <nav class="admin-nav">
      <a class="{dashboard_active}" href="/admin/dashboard">Tổng quan</a>
      <a class="{articles_active}" href="/admin">Duyệt bài</a>
      <a class="{upload_active}" href="/admin/upload">Tải ấn phẩm</a>
      <a href="/client" target="_blank" rel="noopener">Xem client</a>
    </nav>
    <form method="post" action="/admin/logout">
      <button class="button ghost full" type="submit">Đăng xuất</button>
    </form>
  </aside>
  <main class="admin-shell">
    {body}
  </main>
  {render_admin_loading_overlay()}
  {render_scroll_top_button()}
</body>
</html>"""


def render_admin_loading_overlay():
    return """
  <div class="admin-loading-overlay" data-admin-loading aria-hidden="true">
    <div class="admin-loading-card" role="status" aria-live="polite">
      <div class="admin-loading-spinner" aria-hidden="true"></div>
      <strong data-admin-loading-title>Đang xử lý duyệt bài...</strong>
      <p>Vui lòng chờ, hệ thống đang cập nhật trạng thái và tạo ấn phẩm.</p>
    </div>
  </div>"""


def render_auth_page(title, body):
    return f"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} - Quản trị PNews</title>
  <link rel="stylesheet" href="/assets/styles.css?v={ASSET_VERSION}">
  <script src="/assets/app.js?v={ASSET_VERSION}" defer></script>
</head>
<body class="auth-app">
  <main class="auth-shell">
    {body}
  </main>
</body>
</html>"""


def render_scroll_top_button():
    return """
  <button class="scroll-top-button" type="button" data-scroll-top aria-label="Quay về đầu trang" title="Quay về đầu trang">
    <span class="scroll-top-icon" aria-hidden="true">
      <span></span>
      <span></span>
      <span></span>
    </span>
  </button>"""


def render_chat_widget():
    chips = "".join(
        f'<button class="chatbot-chip" type="button" data-chat-suggestion="{escape(suggestion)}">{escape(suggestion)}</button>'
        for suggestion in CHAT_SUGGESTIONS
    )
    return f"""
  <section class="chatbot-widget" data-chatbot>
    <button class="chatbot-toggle" type="button" data-chat-toggle aria-expanded="false">
      <span aria-hidden="true">💬</span>
      <strong>Hỏi PNews</strong>
    </button>
    <div class="chatbot-panel" data-chat-panel aria-hidden="true">
      <header class="chatbot-head">
        <div>
          <strong>PNews Assistant</strong>
          <span>Hỏi nhanh tin tức mới nhất</span>
        </div>
        <button class="chatbot-close" type="button" data-chat-close aria-label="Đóng chat">×</button>
      </header>
      <div class="chatbot-messages" data-chat-messages>
        <article class="chat-message bot">
          <p>Xin chào, tôi có thể giúp bạn tìm tin mới, tin theo chủ đề, nguồn báo hoặc tóm tắt các bài đã đăng trên PNews.</p>
        </article>
      </div>
      <div class="chatbot-suggestions" data-chat-suggestions>{chips}</div>
      <form class="chatbot-form" data-chat-form>
        <input name="message" maxlength="500" autocomplete="off" placeholder="Nhập câu hỏi về tin tức..." required>
        <button class="button primary compact" type="submit">Gửi</button>
      </form>
    </div>
  </section>"""


def client_filter_url(q="", source="", topic="", date_filter=None, page=1):
    parts = []
    if q:
        parts.append(f"q={quote(q)}")
    if source:
        parts.append(f"source={quote(source)}")
    if topic:
        parts.append(f"topic={quote(topic)}")
    if date_filter == "":
        parts.append("date=all")
    elif date_filter:
        parts.append(f"date={quote(str(date_filter))}")
    if int(page or 1) > 1:
        parts.append(f"page={int(page)}")
    return "/client" + (("?" + "&".join(parts)) if parts else "")


def render_client_home(query):
    q = (query.get("q") or [""])[0].strip()
    topic = resolve_client_topic((query.get("topic") or [""])[0].strip())
    source = (query.get("source") or [""])[0].strip()
    date_filter = admin_date_filter_from_query(query)
    page = parse_page(query)
    total = count_articles(
        status="approved",
        q=q,
        topic=topic,
        source=source,
        date_filter=date_filter,
        canonical_topic=True,
    )
    page = min(page, max(1, (total + CLIENT_PAGE_SIZE - 1) // CLIENT_PAGE_SIZE))
    articles = query_articles(
        status="approved",
        q=q,
        topic=topic,
        source=source,
        date_filter=date_filter,
        limit=CLIENT_PAGE_SIZE,
        offset=(page - 1) * CLIENT_PAGE_SIZE,
        canonical_topic=True,
    )
    updated_images = ensure_generated_images_for_rows(articles, limit=CLIENT_PAGE_SIZE)
    if updated_images:
        articles = query_articles(
            status="approved",
            q=q,
            topic=topic,
            source=source,
            date_filter=date_filter,
            limit=CLIENT_PAGE_SIZE,
            offset=(page - 1) * CLIENT_PAGE_SIZE,
            canonical_topic=True,
        )
    topics = get_client_topics()
    sources = get_sources(status="approved")
    latest_active = not q and not source and not topic
    ptit_active = topic == "Tin tức PTIT"
    general_active = topic == "Tin tức chung"
    quick_filters = f"""
      <div class="client-quick-filters" aria-label="Bộ lọc nhanh">
        <a class="quick-filter {'active' if latest_active else ''}" href="{client_filter_url(date_filter=date_filter)}">Tin mới nhất</a>
        <a class="quick-filter {'active' if general_active else ''}" href="{client_filter_url(topic='Tin tức chung', date_filter=date_filter)}">Tin tức chung</a>
        <a class="quick-filter {'active' if ptit_active else ''}" href="{client_filter_url(topic='Tin tức PTIT', date_filter=date_filter)}">Tin tức PTIT</a>
      </div>
    """
    cards = "\n".join(render_client_card(article) for article in articles)
    if not cards:
        cards = """
        <section class="empty-state">
          <h2>Chưa có bài đã duyệt</h2>
          <p>Vào trang admin để duyệt bài. Sau khi duyệt, bài sẽ xuất hiện tại khu vực client.</p>
          <a class="button primary" href="/admin">Mở admin</a>
        </section>
        """

    topic_options = render_select_options(topics, topic, "Tất cả chủ đề")
    source_options = render_select_options(sources, source, "Tất cả tờ báo")
    pagination = render_pagination(
        "/client",
        page,
        total,
        CLIENT_PAGE_SIZE,
        {"q": q, "source": source, "topic": topic, "date": date_filter or "all"},
    )
    today_link = client_filter_url(q, source, topic, date_filter=today_iso_date())
    all_dates_link = client_filter_url(q, source, topic, date_filter="")
    date_controls = render_date_filter_controls(date_filter, today_link, all_dates_link)

    body = f"""
    <section class="client-hero">
      <div>
        <p class="eyebrow">Client demo</p>
        <h1>Ấn phẩm đã duyệt</h1>
        <p class="hero-copy">Không gian xem trước các bài đã được admin chọn xuất bản. Luồng này có thể nối tiếp sang tự động đăng bài, chatbot hoặc thông báo Zalo về sau.</p>
      </div>
    </section>
    <section class="client-filter-panel">
      {quick_filters}
      <form class="filter-bar client-filter" method="get" action="/client" data-auto-submit>
        <input type="search" name="q" placeholder="Tìm tiêu đề, tóm tắt, nguồn..." value="{escape(q)}">
        <select name="source" aria-label="Lọc theo tờ báo">{source_options}</select>
        <select name="topic">{topic_options}</select>
        {date_controls}
      </form>
    </section>
    <section class="article-grid">{cards}</section>
    {pagination}
    """
    return render_client_page("Client", body)


def render_client_card(article):
    image_url = article_image_url(article)
    link_attrs = article_link_attrs(article)
    summary = article_display_summary(article)
    topic_label = client_topic_label(article)
    image = (
        f'<img src="{escape(image_url)}" alt="{escape(article["title"])}" loading="lazy">'
        if image_url
        else '<div class="image-fallback">PNews</div>'
    )
    return f"""
    <article class="article-card">
      <a class="article-image" {link_attrs}>{image}</a>
      <div class="article-body">
        <a class="article-body-link" {link_attrs}>
          <span class="meta-line">
            <span>{escape(article['source'] or 'PNews')}</span>
            <span>{escape(topic_label)}</span>
            <span>Ngày đăng: {escape(article['published_at'] or article['crawled_at'] or 'Chưa rõ')}</span>
          </span>
          <strong>{escape(article['title'])}</strong>
          <span class="article-summary">{escape(summary)}</span>
        </a>
        <a class="text-link" {link_attrs}>Xem bài viết</a>
      </div>
    </article>
    """


def render_article_detail(article_id):
    article = get_article(article_id)
    if not article or article["status"] != "approved":
        return render_not_found()
    image_url = article_image_url(article)
    image = (
        f'<img src="{escape(image_url)}" alt="{escape(article["title"])}">'
        if image_url
        else '<div class="image-fallback detail">PNews</div>'
    )
    source_link = (
        f'<a class="button ghost" href="{escape(article["url"])}" target="_blank" rel="noopener">Mở bài gốc</a>'
        if article["url"]
        else ""
    )
    title_link = article_link_attrs(article)
    summary = article_display_summary(article)
    topic_label = client_topic_label(article)
    body = f"""
    <article class="detail-layout">
      <a class="detail-media" {title_link}>{image}</a>
      <div class="detail-content">
        <a class="text-link" href="/client">Quay lại client</a>
        <div class="meta-line">
          <span>{escape(article['source'])}</span>
          <span>{escape(topic_label)}</span>
          <span>Ngày đăng: {escape(article['published_at'] or article['crawled_at'] or 'Chưa rõ')}</span>
        </div>
        <h1><a {title_link}>{escape(article['title'])}</a></h1>
        <a class="detail-summary" {title_link}>{escape(summary)}</a>
        <div class="detail-actions">{source_link}</div>
      </div>
    </article>
    """
    return render_client_page(article["title"], body)


def render_admin_login(error=""):
    error_html = f'<p class="form-error">{escape(error)}</p>' if error else ""
    body = f"""
    <section class="login-panel">
      <div>
        <img class="site-logo login-logo" src="{SITE_LOGO_URL}" alt="PNews">
        <p class="eyebrow">Admin</p>
        <h1>Đăng nhập duyệt bài</h1>
        <p>Nhập tên đăng nhập và mật khẩu để truy cập khu vực quản trị, duyệt bài và xuất bản ấn phẩm.</p>
      </div>
      <form class="panel-form" method="post" action="/admin/login">
        {error_html}
        <label>Tên đăng nhập<input name="username" autocomplete="username" required></label>
        <label>Mật khẩu<input name="password" type="password" autocomplete="current-password" required></label>
        <button class="button primary full" type="submit">Đăng nhập</button>
      </form>
    </section>
    """
    return render_auth_page("Đăng nhập admin", body)


def render_dashboard_card(card):
    classes = f"dashboard-card tone-{escape(card['tone'])}"
    if card.get("wide"):
        classes += " wide"
    return f"""
        <article class="{classes}">
          <span>{escape(card['label'])}</span>
          <strong>{escape(card['value'])}</strong>
        </article>
        """


def render_dashboard_card_sections(cards):
    groups = [
        ("overview", "Tổng quan bài viết"),
        ("facebook", "Hoạt động Facebook"),
        ("quality", "Chất lượng dữ liệu"),
    ]
    sections = []
    for group_key, group_label in groups:
        group_cards = [card for card in cards if card.get("group") == group_key]
        if not group_cards:
            continue
        rendered_cards = "\n".join(render_dashboard_card(card) for card in group_cards)
        sections.append(
            f"""
            <section class="dashboard-card-section">
              <div class="dashboard-card-section-heading">
                <h2>{escape(group_label)}</h2>
              </div>
              <div class="dashboard-grid">{rendered_cards}</div>
            </section>
            """
        )
    remaining_cards = [card for card in cards if card.get("group") not in {key for key, _label in groups}]
    if remaining_cards:
        sections.append(f'<section class="dashboard-grid">{"".join(render_dashboard_card(card) for card in remaining_cards)}</section>')
    return "\n".join(sections)


def render_admin_overview_dashboard():
    stats = get_admin_dashboard_stats()
    if not stats["ready"]:
        body = f"""
        <section class="admin-head">
          <div>
            <p class="eyebrow">Dashboard</p>
            <h1>Tổng quan PNews</h1>
            <p>Theo dõi nhanh dữ liệu bài viết, nguồn báo, trạng thái duyệt và chất lượng crawl.</p>
          </div>
          <div class="admin-actions">
            <a class="button ghost" href="/admin">Về danh sách duyệt</a>
          </div>
        </section>
        <section class="empty-state">
          <h2>Chưa thể hiển thị dashboard</h2>
          <p>{escape(stats["error"] or "Dữ liệu CMS chưa sẵn sàng.")}</p>
          <p><code>{escape(stats["db_path"])}</code></p>
        </section>
        """
        return render_admin_page("Dashboard", body, active_nav="dashboard")

    cards = render_dashboard_card_sections(stats["cards"])
    source_rows = render_dashboard_metric_rows(stats["source_counts"], "Chưa có nguồn báo nào.")
    topic_rows = render_dashboard_metric_rows(stats["topic_counts"], "Chưa có dữ liệu chủ đề.")
    recent_rows = render_dashboard_recent_articles(stats["recent_articles"])
    warning_rows = render_dashboard_warnings(stats["warnings"]["items"])
    status_rows = render_dashboard_status_rows(stats["raw_status_counts"])

    body = f"""
    <section class="admin-head">
      <div>
        <p class="eyebrow">Dashboard</p>
        <h1>Tổng quan PNews</h1>
        <p>Theo dõi nhanh tình trạng dữ liệu tin tức, nguồn báo, chủ đề, trạng thái duyệt và hoạt động crawl.</p>
      </div>
      {render_admin_head_actions("dashboard")}
    </section>
    <div class="dashboard-card-sections">{cards}</div>
    <section class="dashboard-panels">
      <article class="dashboard-panel">
        <div class="panel-heading">
          <h2>Thống kê theo nguồn báo</h2>
          <span>{len(stats["source_counts"])} nguồn</span>
        </div>
        <div class="metric-list">{source_rows}</div>
      </article>
      <article class="dashboard-panel">
        <div class="panel-heading">
          <h2>Top chủ đề</h2>
          <span>Ưu tiên content_topic</span>
        </div>
        <div class="metric-list">{topic_rows}</div>
      </article>
    </section>
    <section class="dashboard-panels compact-panels">
      <article class="dashboard-panel">
        <div class="panel-heading">
          <h2>Trạng thái trong database</h2>
          <span>Mapping mềm theo nhóm</span>
        </div>
        <div class="status-breakdown">{status_rows}</div>
      </article>
      <article class="dashboard-panel">
        <div class="panel-heading">
          <h2>Cảnh báo dữ liệu</h2>
          <span>Ưu tiên xử lý</span>
        </div>
        <div class="warning-list">{warning_rows}</div>
      </article>
    </section>
    <section class="dashboard-panel">
      <div class="panel-heading">
        <h2>10 bài mới crawl gần đây</h2>
        <span>{escape(stats["latest_crawled_at"] or "Chưa có ngày đăng")}</span>
      </div>
      <div class="dashboard-table-wrap">
        <table class="dashboard-table">
          <thead>
            <tr>
              <th>Tiêu đề</th>
              <th>Nguồn</th>
              <th>Chủ đề</th>
              <th>Trạng thái</th>
              <th>Ngày đăng</th>
              <th>Liên kết</th>
            </tr>
          </thead>
          <tbody>{recent_rows}</tbody>
        </table>
      </div>
    </section>
    """
    return render_admin_page("Dashboard", body, active_nav="dashboard")


def render_dashboard_metric_rows(rows, empty_label):
    if not rows:
        return f'<p class="dashboard-empty">{escape(empty_label)}</p>'
    max_total = max(row["total"] for row in rows) or 1
    output = []
    for row in rows:
        width = max(4, int(row["total"] * 100 / max_total))
        output.append(
            f"""
            <div class="metric-row">
              <div>
                <strong>{escape(row['label'])}</strong>
                <span>{escape(row['total'])} bài</span>
              </div>
              <i style="width: {width}%"></i>
            </div>
            """
        )
    return "\n".join(output)


def render_dashboard_status_rows(rows):
    if not rows:
        return '<p class="dashboard-empty">Schema hiện không có cột status.</p>'
    return "\n".join(
        f"""
        <div class="status-row">
          <span>{escape(STATUS_LABELS.get(row['status'], row['status']))}</span>
          <strong>{escape(row['total'])}</strong>
        </div>
        """
        for row in rows
    )


def render_dashboard_warnings(warnings):
    if not warnings:
        return """
        <div class="warning-item level-ok">
          <strong>Dữ liệu ổn</strong>
          <span>Chưa phát hiện cảnh báo nổi bật.</span>
        </div>
        """
    return "\n".join(
        f"""
        <div class="warning-item level-{escape(item['level'])}">
          <strong>{escape(item['label'])}: {escape(item['value'])}</strong>
          <span>{escape(item['detail'])}</span>
        </div>
        """
        for item in warnings
    )


def render_dashboard_recent_articles(articles):
    if not articles:
        return """
        <tr>
          <td colspan="6" class="dashboard-empty-cell">Chưa có bài viết nào trong database.</td>
        </tr>
        """
    rows = []
    for article in articles:
        source_link = (
            f'<a class="text-link" href="{escape(article["url"])}" target="_blank" rel="noopener">Bài gốc</a>'
            if article.get("url")
            else '<span class="muted-text">Thiếu URL</span>'
        )
        admin_link = f'<a class="text-link" href="/admin?q={quote(str(article.get("title") or ""))}">Admin</a>'
        status = article.get("status") or "unknown"
        rows.append(
            f"""
            <tr>
              <td><strong>{escape(article.get('title') or 'Không có tiêu đề')}</strong></td>
              <td>{escape(article.get('source') or 'Không rõ')}</td>
              <td>{escape(article.get('topic') or 'Chưa phân loại')}</td>
              <td><span class="badge status-{escape(normalize_status_group(status))}">{escape(STATUS_LABELS.get(status, status))}</span></td>
              <td>{escape(article.get('published_at') or article.get('crawled_at') or 'Chưa có')}</td>
              <td><div class="table-actions">{source_link}{admin_link}</div></td>
            </tr>
            """
        )
    return "\n".join(rows)


def serialize_chat_response(response):
    return {
        "answer": response.get("answer", ""),
        "articles": [
            serialize_chat_article(article)
            for article in response.get("articles", [])
        ],
        "mode": response.get("mode", "fallback"),
        "provider": response.get("provider", "none"),
    }


def serialize_chat_article(article):
    return {
        "title": article.get("title", ""),
        "summary": article.get("summary", ""),
        "source": article.get("source", ""),
        "category": article.get("category", ""),
        "content_topic": article.get("content_topic", ""),
        "url": article.get("url", ""),
        "thumbnail": article_image_url(article),
        "published_at": article.get("published_at", ""),
        "crawled_at": article.get("crawled_at", ""),
    }


def render_admin_dashboard(query):
    status = (query.get("status") or ["pending"])[0]
    if status not in STATUS_LABELS:
        status = "pending"
    q = (query.get("q") or [""])[0].strip()
    source = (query.get("source") or [""])[0].strip()
    topic = resolve_client_topic((query.get("topic") or [""])[0].strip())
    date_filter = admin_date_filter_from_query(query)
    notice = (query.get("notice") or [""])[0].strip()
    page = parse_page(query)
    counts = get_counts()
    total = count_articles(
        status=status,
        q=q,
        source=source,
        topic=topic,
        date_filter=date_filter,
        canonical_topic=True,
    )
    page = min(page, max(1, (total + ADMIN_PAGE_SIZE - 1) // ADMIN_PAGE_SIZE))
    articles = query_articles(
        status=status,
        q=q,
        source=source,
        topic=topic,
        date_filter=date_filter,
        limit=ADMIN_PAGE_SIZE,
        offset=(page - 1) * ADMIN_PAGE_SIZE,
        canonical_topic=True,
    )
    updated_images = ensure_generated_images_for_rows(articles, limit=ADMIN_PAGE_SIZE)
    if updated_images:
        articles = query_articles(
            status=status,
            q=q,
            source=source,
            topic=topic,
            date_filter=date_filter,
            limit=ADMIN_PAGE_SIZE,
            offset=(page - 1) * ADMIN_PAGE_SIZE,
            canonical_topic=True,
        )
    sources = get_sources()
    topics = get_client_topics(status=None)
    source_options = render_select_options(sources, source, "Tất cả tờ báo")
    topic_options = render_select_options(topics, topic, "Tất cả chủ đề")

    tabs = "".join(
        f'<a class="status-tab {"active" if status == key else ""}" href="{admin_filter_url(key, q, source, topic, date_filter=date_filter)}">{label}<strong>{counts.get(key, 0)}</strong></a>'
        for key, label in STATUS_LABELS.items()
    )
    rows = "\n".join(render_admin_article(article) for article in articles)
    if not rows:
        rows = '<div class="empty-state compact"><h2>Không có bài trong mục này</h2><p>Thử đổi bộ lọc hoặc tải thêm ấn phẩm mới.</p></div>'

    bulk_actions = render_bulk_actions(status)
    notice_html = f'<p class="form-success">{escape(notice)}</p>' if notice else ""
    pagination = render_pagination(
        "/admin",
        page,
        total,
        ADMIN_PAGE_SIZE,
        {"status": status, "q": q, "source": source, "topic": topic, "date": date_filter or "all"},
    )
    today_link = admin_filter_url(status, q, source, topic, date_filter=today_iso_date())
    all_dates_link = admin_filter_url(status, q, source, topic, date_filter="")
    date_controls = render_date_filter_controls(date_filter, today_link, all_dates_link)

    body = f"""
    <section class="admin-head">
      <div>
        <p class="eyebrow">Bảng điều khiển</p>
        <h1>Duyệt ấn phẩm</h1>
        <p>Chọn từng bài hoặc chọn nhiều bài cùng lúc để đưa sang client, từ chối hoặc xóa khỏi hàng đợi.</p>
      </div>
      {render_admin_head_actions("articles")}
    </section>
    <section class="status-tabs">{tabs}</section>
    <form class="admin-search" method="get" action="/admin" data-auto-submit>
      <input type="hidden" name="status" value="{escape(status)}">
      <input type="search" name="q" placeholder="Tìm trong hàng đợi..." value="{escape(q)}">
      <select name="source" aria-label="Lọc theo tờ báo">{source_options}</select>
      <select name="topic" aria-label="Lọc theo chủ đề">{topic_options}</select>
      {date_controls}
    </form>
    {notice_html}
    <form class="bulk-review-form" method="post" action="/admin/bulk">
      <input type="hidden" name="return_status" value="{escape(status)}">
      <input type="hidden" name="return_q" value="{escape(q)}">
      <input type="hidden" name="return_source" value="{escape(source)}">
      <input type="hidden" name="return_topic" value="{escape(topic)}">
      <input type="hidden" name="return_date" value="{escape(date_filter or 'all')}">
      <input type="hidden" name="return_page" value="{escape(page)}">
      <div class="bulk-toolbar">
        <label class="select-all-row">
          <input type="checkbox" data-select-all>
          <span>Chọn tất cả bài đang hiển thị</span>
        </label>
        <div class="bulk-actions">
          {bulk_actions}
        </div>
      </div>
      <section class="admin-list">{rows}</section>
      {pagination}
    </form>
    """
    return render_admin_page("Admin", body)


def admin_filter_url(status, q="", source="", topic="", date_filter=None, notice="", page=1):
    try:
        page_number = max(1, int(page or 1))
    except (TypeError, ValueError):
        page_number = 1

    parts = [f"status={quote(status)}"]
    if q:
        parts.append(f"q={quote(q)}")
    if source:
        parts.append(f"source={quote(source)}")
    if topic:
        parts.append(f"topic={quote(topic)}")
    if date_filter == "":
        parts.append("date=all")
    elif date_filter:
        parts.append(f"date={quote(str(date_filter))}")
    if page_number > 1:
        parts.append(f"page={page_number}")
    if notice:
        parts.append(f"notice={quote(notice)}")
    return "/admin?" + "&".join(parts)


def render_bulk_actions(status):
    actions_by_status = {
        "pending": [
            ("approve", "Duyệt đã chọn", "success"),
            ("reject", "Từ chối đã chọn", "ghost"),
            ("delete", "Xóa đã chọn", "danger"),
        ],
        "approved": [
            ("reject", "Gỡ khỏi client", "ghost"),
            ("delete", "Xóa đã chọn", "danger"),
        ],
        "rejected": [
            ("approve", "Duyệt lại", "success"),
            ("delete", "Xóa đã chọn", "danger"),
        ],
        "deleted": [
            ("restore", "Khôi phục đã chọn", "ghost"),
        ],
    }
    buttons = []
    for action, label, variant in actions_by_status.get(status, []):
        confirm = ' data-requires-selection data-confirm-bulk="Bạn chưa chọn bài nào." disabled aria-disabled="true"' if action else ""
        buttons.append(
            f'<button class="button {variant}" name="bulk_action" value="{action}" type="submit"{confirm}>{label}</button>'
        )
    if status == "approved":
        buttons.insert(
            0,
            '<button class="button ghost" name="bulk_action" value="clear_facebook" type="submit" data-requires-selection data-confirm-bulk="Bạn chưa chọn bài nào." data-confirm="Gỡ tag Đã đăng FB cho các bài đã chọn? Thao tác này không xóa bài trên Facebook." disabled aria-disabled="true">Gỡ tag FB đã chọn</button>',
        )
        buttons.insert(
            0,
            '<button class="button primary" name="bulk_action" value="publish_facebook" type="submit" formaction="/admin/articles/publish-facebook-bulk" data-requires-selection data-confirm-bulk="Bạn chưa chọn bài nào." data-confirm="Bạn có chắc chắn muốn đăng các bài đã chọn lên Facebook Page không?" disabled aria-disabled="true">Đăng Facebook các bài đã chọn</button>',
        )
        buttons.insert(
            0,
            '<button class="button primary" type="button" data-export-selected-png data-requires-selection data-confirm-bulk="Bạn chưa chọn bài nào." disabled aria-disabled="true">Export PNG</button>',
        )
    return "".join(buttons)


def render_facebook_status_badge(article):
    data = article_to_dict(article)
    status = article_facebook_status(data)
    label = FACEBOOK_STATUS_LABELS.get(status, status or "Chưa đăng")
    error = data.get("facebook_publish_error") or ""
    title = f' title="{escape(error)}"' if error else ""
    return f'<span class="badge facebook-badge facebook-{escape(status)}"{title}>Facebook: {escape(label)}</span>'


def render_facebook_publish_actions(article):
    data = article_to_dict(article)
    status = article_facebook_status(data)
    permalink = str(data.get("facebook_permalink") or "").strip()
    posted = int(data.get("facebook_posted") or 0) == 1 or status == "success"
    actions = []

    if posted:
        actions.append(
            '<button class="button ghost" type="button" disabled aria-disabled="true">Đã đăng Facebook</button>'
        )
        actions.append(
            f'<button class="button ghost" type="submit" formaction="/admin/articles/{data["id"]}/clear-facebook" data-confirm="Gỡ tag Đã đăng FB để có thể đăng lại bài này? Thao tác này không xóa bài trên Facebook.">Gỡ tag FB</button>'
        )
    elif status == "posting":
        actions.append(
            '<button class="button ghost" type="button" disabled aria-disabled="true">Đang đăng Facebook</button>'
        )
    else:
        label = "Thử lại Facebook" if status == "failed" else "Đăng Facebook"
        actions.append(
            f'<button class="button primary" type="submit" formaction="/admin/articles/{data["id"]}/publish-facebook" data-confirm="Bạn có chắc chắn muốn đăng bài này lên Facebook Page không?">{escape(label)}</button>'
        )

    if permalink:
        actions.append(
            f'<a class="button ghost" href="{escape(permalink)}" target="_blank" rel="noopener">Xem trên Facebook</a>'
        )
    return "".join(actions)


def render_facebook_preview(article):
    data = article_to_dict(article)
    if data.get("status") != "approved":
        return ""

    caption = data.get("facebook_caption") or buildFacebookCaption(data)
    image_url = article_image_url(article)
    image = (
        f'<img src="{escape(image_url)}" alt="{escape(data.get("title"))}" loading="lazy">'
        if image_url
        else '<div class="facebook-preview-fallback">PNews</div>'
    )
    source = data.get("source") or "PNews"
    url = str(data.get("url") or "").strip()
    link = (
        f'<a href="{escape(url)}" target="_blank" rel="noopener">{escape(url)}</a>'
        if url
        else '<span>Không có link bài viết</span>'
    )
    return f"""
        <details class="facebook-preview">
          <summary>Facebook Preview</summary>
          <div class="facebook-preview-body">
            <div class="facebook-preview-image">{image}</div>
            <div class="facebook-preview-copy">
              <pre>{escape(caption)}</pre>
              <div class="facebook-preview-meta">
                <span>Nguồn: {escape(source)}</span>
                <span>{link}</span>
              </div>
            </div>
          </div>
        </details>
    """


def render_admin_article(article):
    image_url = article_image_url(article)
    link_attrs = article_link_attrs(article)
    click_attrs = article_click_attrs(article)
    summary_text = article_display_summary(article, context="admin")
    topic_label = client_topic_label(article)
    image = (
        f'<img src="{escape(image_url)}" alt="{escape(article["title"])}" loading="lazy">'
        if image_url
        else '<div class="image-fallback admin">PNews</div>'
    )
    approve = action_button(article["id"], "approve", "Duyệt", "success")
    reject = action_button(article["id"], "reject", "Từ chối", "ghost")
    delete = action_button(article["id"], "delete", "Xóa", "danger")
    restore = action_button(article["id"], "restore", "Khôi phục", "ghost")
    export_png = (
        f'<a class="button primary" href="/admin/articles/{article["id"]}/export.png" download>Export PNG</a>'
        if article["status"] == "approved"
        else ""
    )
    facebook_badge = render_facebook_status_badge(article) if article["status"] == "approved" else ""
    facebook_actions = render_facebook_publish_actions(article) if article["status"] == "approved" else ""
    facebook_preview = render_facebook_preview(article)

    actions = {
        "pending": approve + reject + delete,
        "approved": facebook_actions + export_png + reject + delete,
        "rejected": approve + delete,
        "deleted": restore,
    }.get(article["status"], approve + delete)
    date_items = [
        f"Ngày đăng: {escape(article['published_at'] or article['crawled_at'] or 'Chưa rõ')}",
        f"Crawl: {escape(article['crawled_at'] or 'Chưa rõ')}",
        f"Cập nhật: {escape(article['updated_at'] or 'Chưa rõ')}",
    ]
    if article["approved_at"]:
        date_items.append(f"Duyệt ngày: {escape(article['approved_at'])}")
    elif article["reviewed_at"] and article["status"] == "rejected":
        date_items.append(f"Từ chối ngày: {escape(article['reviewed_at'])}")
    if article["deleted_at"]:
        date_items.append(f"Xóa ngày: {escape(article['deleted_at'])}")
    date_line = "".join(f"<span>{item}</span>" for item in date_items)

    return f"""
    <article class="review-item">
      <label class="review-check" title="Chọn bài này">
        <input type="checkbox" name="article_ids" value="{article['id']}" data-row-check>
      </label>
      <a class="review-image" {link_attrs}>{image}</a>
      <div class="review-content">
        <div class="meta-line">
          <span>{escape(article['source'] or 'Admin')}</span>
          <span>{escape(topic_label or 'Chưa phân loại')}</span>
          <span class="badge">{escape(STATUS_LABELS.get(article['status'], article['status']))}</span>
          {facebook_badge}
        </div>
        <div class="review-click-zone" {click_attrs}>
          <h2><a class="review-title-link" {link_attrs}>{escape(article['title'])}</a></h2>
          <p><a class="review-summary-link" {link_attrs}>{escape(summary_text)}</a></p>
        </div>
        {facebook_preview}
        <div class="date-line">{date_line}</div>
      </div>
      <div class="review-actions">{actions}</div>
    </article>
    """


def action_button(article_id, action, label, variant):
    return f"""
      <button class="button {variant}" name="single_action" value="{action}:{article_id}" type="submit">{escape(label)}</button>
    """


def auto_send_telegram_notice(article_ids):
    try:
        result = NotificationService(DB_PATH).send_selected_articles_to_telegram(article_ids)
        return (
            "Telegram tự động: gửi thành công "
            f"{result['sent']} bài, bỏ qua {result['skipped']} bài, lỗi {result['failed']} bài."
        )
    except Exception as exc:
        return f"Telegram tự động: chưa gửi được ({str(exc)[:180]})."


def auto_send_telegram_notice_background(article_ids):
    clean_ids = [int(article_id) for article_id in article_ids or [] if str(article_id).isdigit()]
    if not clean_ids:
        return ""

    def worker():
        notice = auto_send_telegram_notice(clean_ids)
        LOGGER.info("%s", notice)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return "Telegram tự động: đang gửi nền."


def render_upload_form(error="", success=""):
    error_html = f'<p class="form-error">{escape(error)}</p>' if error else ""
    success_html = f'<p class="form-success">{escape(success)}</p>' if success else ""
    body = f"""
    <section class="admin-head">
      <div>
        <p class="eyebrow">Upload</p>
        <h1>Tải ấn phẩm mới</h1>
        <p>Mỗi ảnh upload sẽ đi vào hàng đợi duyệt. Nếu chọn đăng ngay, bài sẽ xuất hiện trên client lập tức.</p>
      </div>
      {render_admin_head_actions("upload")}
    </section>
    <form class="upload-form" method="post" action="/admin/upload" enctype="multipart/form-data">
      {error_html}
      {success_html}
      <label>Tiêu đề<input name="title" required placeholder="Nhập tiêu đề bài viết hoặc ấn phẩm"></label>
      <label>Tóm tắt<textarea name="summary" rows="4" placeholder="Nội dung ngắn hiển thị trên client"></textarea></label>
      <div class="form-grid">
        <label>Nguồn<input name="source" placeholder="PNews, VNExpress..."></label>
        <label>Chủ đề<input name="content_topic" placeholder="Công nghệ, giáo dục..."></label>
        <label>Chuyên mục<input name="category" placeholder="Tin tức, sự kiện..."></label>
        <label>Link bài gốc<input name="url" type="url" placeholder="https://..."></label>
      </div>
      <label>Ảnh ấn phẩm<input name="image" type="file" accept="image/*"></label>
      <label class="checkbox-row"><input name="publish_now" type="checkbox"> Duyệt và đăng ngay lên client</label>
      <button class="button primary" type="submit">Lưu ấn phẩm</button>
    </form>
    """
    return render_admin_page("Tải ấn phẩm", body, active_nav="upload")


def render_not_found():
    body = """
    <section class="empty-state">
      <h1>Không tìm thấy trang</h1>
      <p>Nội dung có thể chưa được duyệt hoặc đã bị xóa.</p>
      <a class="button primary" href="/client">Về client</a>
    </section>
    """
    return render_client_page("404", body)


def parse_form_urlencoded(body):
    parsed = parse_qs(body.decode("utf-8", errors="replace"))
    return {key: values[0] for key, values in parsed.items()}


def parse_form_urlencoded_multi(body):
    return parse_qs(body.decode("utf-8", errors="replace"))


def parse_multipart(body, content_type):
    boundary_match = re.search(r"boundary=(.+)", content_type)
    if not boundary_match:
        return {}, {}
    boundary = boundary_match.group(1).strip().strip('"').encode()
    fields = {}
    files = {}
    delimiter = b"--" + boundary

    for raw_part in body.split(delimiter):
        raw_part = raw_part.strip()
        if not raw_part or raw_part == b"--":
            continue
        if raw_part.endswith(b"--"):
            raw_part = raw_part[:-2].strip()
        header_blob, separator, content = raw_part.partition(b"\r\n\r\n")
        if not separator:
            continue
        content = content.rstrip(b"\r\n")
        headers = parse_part_headers(header_blob)
        disposition = headers.get("content-disposition", "")
        name_match = re.search(r'name="([^"]+)"', disposition)
        if not name_match:
            continue
        name = name_match.group(1)
        filename_match = re.search(r'filename="([^"]*)"', disposition)
        if filename_match and filename_match.group(1):
            files[name] = {
                "filename": Path(filename_match.group(1)).name,
                "content_type": headers.get("content-type", "application/octet-stream"),
                "content": content,
            }
        else:
            fields[name] = content.decode("utf-8", errors="replace")
    return fields, files


def parse_part_headers(header_blob):
    headers = {}
    for line in header_blob.decode("utf-8", errors="replace").split("\r\n"):
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    return headers


class CMSHandler(BaseHTTPRequestHandler):
    server_version = "PNewsCMS/1.0"

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/":
            self.redirect("/client")
        elif path == "/health":
            db_status = "ok"
            status_code = HTTPStatus.OK
            try:
                with connect_db() as conn:
                    conn.execute("SELECT 1").fetchone()
            except Exception as e:
                db_status = f"error: {str(e)}"
                status_code = HTTPStatus.SERVICE_UNAVAILABLE
                try:
                    DATA_DIR.mkdir(parents=True, exist_ok=True)
                except Exception:
                    pass
            self.respond_json({
                "status": "ok" if status_code == HTTPStatus.OK else "degraded",
                "database": db_status,
                "time": now_iso(),
                "app": "PNews"
            }, status=status_code)
        elif path == "/client":
            self.respond_html(render_client_home(query))
        elif path.startswith("/client/article/"):
            article_id = path.removeprefix("/client/article/")
            if article_id.isdigit():
                self.respond_html(render_article_detail(int(article_id)))
            else:
                self.respond_html(render_not_found(), HTTPStatus.NOT_FOUND)
        elif path == "/admin":
            if self.is_authenticated():
                self.respond_html(render_admin_dashboard(query))
            else:
                self.respond_html(render_admin_login())
        elif path in {"/admin/dashboard", "/admin/overview", "/dashboard"}:
            self.require_admin(lambda: self.respond_html(render_admin_overview_dashboard()))
        elif path in {"/admin/dashboarh", "/admin/dashbord"}:
            self.redirect("/admin/dashboard")
        elif path == "/admin/upload":
            self.require_admin(lambda: self.respond_html(render_upload_form()))
        elif re.fullmatch(r"/admin/articles/\d+/export\.png", path):
            self.require_admin(lambda: self.handle_article_export(path))
        elif path == "/api/chat/suggestions":
            self.respond_json({"suggestions": CHAT_SUGGESTIONS})
        elif path.startswith("/api/articles"):
            self.respond_json(self.public_articles_json(query))
        elif path.startswith("/assets/"):
            self.serve_asset(path.removeprefix("/assets/"))
        elif path.startswith("/media/"):
            self.serve_media(path.removeprefix("/media/"))
        else:
            self.respond_html(render_not_found(), HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/admin/login":
            self.handle_login()
        elif path == "/admin/logout":
            self.handle_logout()
        elif path == "/admin/upload":
            self.require_admin(self.handle_upload)
        elif path == "/admin/bulk":
            self.require_admin(self.handle_bulk_action)
        elif re.fullmatch(r"/admin/articles/\d+/publish-facebook", path):
            self.require_admin(lambda: self.handle_facebook_publish_single(path))
        elif re.fullmatch(r"/admin/articles/\d+/clear-facebook", path):
            self.require_admin(lambda: self.handle_facebook_clear_single(path))
        elif path == "/admin/articles/publish-facebook-bulk":
            self.require_admin(self.handle_facebook_publish_bulk)
        elif path.startswith("/admin/articles/"):
            self.require_admin(lambda: self.handle_article_action(path))
        elif path == "/api/chat":
            self.handle_chat_api()
        else:
            self.respond_html(render_not_found(), HTTPStatus.NOT_FOUND)

    def handle_login(self):
        fields = self.read_form()
        username = fields.get("username", "")
        password = fields.get("password", "")
        expected_password = ADMIN_ACCOUNTS.get(username)
        if expected_password and secrets.compare_digest(expected_password, password):
            session_id = secrets.token_urlsafe(32)
            SESSIONS.add(session_id)
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/admin")
            self.send_header("Set-Cookie", f"{SESSION_COOKIE}={session_id}; HttpOnly; SameSite=Lax; Path=/")
            self.send_no_cache_headers()
            self.end_headers()
            return
        if not ADMIN_ACCOUNTS:
            self.respond_html(render_admin_login("Chưa cấu hình tài khoản admin."), HTTPStatus.UNAUTHORIZED)
            return
        self.respond_html(render_admin_login("Sai thông tin đăng nhập."), HTTPStatus.UNAUTHORIZED)

    def handle_logout(self):
        session_id = self.get_session_id()
        if session_id in SESSIONS:
            SESSIONS.remove(session_id)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/admin")
        self.send_header("Set-Cookie", f"{SESSION_COOKIE}=; Max-Age=0; Path=/")
        self.send_no_cache_headers()
        self.end_headers()

    def handle_upload(self):
        success = "Đã lưu ấn phẩm vào hệ thống."
        try:
            content_type = self.headers.get("Content-Type", "")
            body = self.read_body()
            fields, files = parse_multipart(body, content_type)
            article_id, status = create_uploaded_article(fields, files.get("image"))
            if status == "approved":
                success += " " + auto_send_telegram_notice([article_id])
        except ValueError as exc:
            self.respond_html(render_upload_form(error=str(exc)), HTTPStatus.BAD_REQUEST)
            return
        self.respond_html(render_upload_form(success=success))

    def handle_bulk_action(self):
        fields = self.read_form_multi()
        status_map = {
            "approve": "approved",
            "reject": "rejected",
            "delete": "deleted",
            "restore": "pending",
        }
        return_status = (fields.get("return_status") or ["pending"])[0]
        return_q = (fields.get("return_q") or [""])[0].strip()
        return_source = (fields.get("return_source") or [""])[0].strip()
        return_topic = (fields.get("return_topic") or [""])[0].strip()
        return_date_raw = (fields.get("return_date") or [today_iso_date()])[0].strip()
        return_date = "" if return_date_raw == "all" else return_date_raw
        return_page = (fields.get("return_page") or ["1"])[0].strip()

        single_action = (fields.get("single_action") or [""])[0]
        if single_action:
            action, _, raw_id = single_action.partition(":")
            article_ids = [raw_id]
        else:
            action = (fields.get("bulk_action") or [""])[0]
            article_ids = fields.get("article_ids", [])

        clean_ids = []
        seen_ids = set()
        for raw_id in article_ids:
            if str(raw_id).isdigit():
                article_id = int(raw_id)
                if article_id not in seen_ids:
                    clean_ids.append(article_id)
                    seen_ids.add(article_id)

        notice = ""
        if action == "clear_facebook" and clean_ids:
            cleared = clear_article_facebook_fields(clean_ids)
            return_status = "approved"
            notice = f"Đã gỡ tag Facebook cho {cleared} bài. Có thể đăng lại các bài này."
        elif action in status_map and clean_ids:
            set_articles_status(clean_ids, status_map[action])
            return_status = "pending" if action == "restore" else status_map[action]
            if action == "approve":
                notice = auto_send_telegram_notice_background(clean_ids)

        self.redirect(
            admin_filter_url(
                return_status,
                return_q,
                return_source,
                return_topic,
                date_filter=return_date,
                notice=notice,
                page=return_page,
            )
        )

    def handle_facebook_publish_single(self, path):
        match = re.fullmatch(r"/admin/articles/(\d+)/publish-facebook", path)
        if not match:
            self.respond_html(render_not_found(), HTTPStatus.NOT_FOUND)
            return

        wants_json = self.request_wants_json()
        fields = {}
        if wants_json and self.headers.get("Content-Length", "0") != "0":
            payload = self.read_json_payload()
            if payload is None:
                return
        else:
            fields = self.read_form_multi()

        result, status_code = publish_article_to_facebook(int(match.group(1)))
        if wants_json:
            self.respond_json(result, status_code)
            return

        notice = result.get("message", "")
        if not result.get("success") and result.get("error"):
            notice = f"{notice} {result['error']}".strip()
        self.redirect(self.admin_return_url_from_fields(fields, default_status="approved", notice=notice))

    def handle_facebook_clear_single(self, path):
        match = re.fullmatch(r"/admin/articles/(\d+)/clear-facebook", path)
        if not match:
            self.respond_html(render_not_found(), HTTPStatus.NOT_FOUND)
            return

        wants_json = self.request_wants_json()
        fields = {}
        if wants_json and self.headers.get("Content-Length", "0") != "0":
            payload = self.read_json_payload()
            if payload is None:
                return
        else:
            fields = self.read_form_multi()

        article_id = int(match.group(1))
        article = article_to_dict(get_article(article_id))
        if not article:
            result = {
                "success": False,
                "message": "Không tìm thấy bài viết.",
                "data": {"article_id": article_id},
            }
            if wants_json:
                self.respond_json(result, HTTPStatus.NOT_FOUND)
                return
            self.redirect(self.admin_return_url_from_fields(fields, default_status="approved", notice=result["message"]))
            return

        cleared = clear_article_facebook_fields([article_id])
        result = {
            "success": bool(cleared),
            "message": "Đã gỡ tag Facebook. Có thể đăng lại bài này.",
            "data": {"article_id": article_id, "cleared": cleared},
        }
        if wants_json:
            self.respond_json(result)
            return

        self.redirect(self.admin_return_url_from_fields(fields, default_status="approved", notice=result["message"]))

    def handle_facebook_publish_bulk(self):
        wants_json = self.request_wants_json()
        fields = {}
        payload = {}
        if wants_json:
            payload = self.read_json_payload()
            if payload is None:
                return
            article_ids = payload.get("article_ids") or []
        else:
            fields = self.read_form_multi()
            article_ids = fields.get("article_ids", [])

        if isinstance(article_ids, (str, int)):
            article_ids = [article_ids]

        clean_ids = [int(raw_id) for raw_id in article_ids if str(raw_id).isdigit()]
        if not clean_ids:
            result = {
                "success": False,
                "message": "Chưa chọn bài viết nào.",
                "results": [],
            }
            if wants_json:
                self.respond_json(result, HTTPStatus.BAD_REQUEST)
            else:
                self.redirect(
                    self.admin_return_url_from_fields(
                        fields,
                        default_status="approved",
                        notice=result["message"],
                    )
                )
            return

        delay_seconds = payload.get("delay_seconds", 1.2) if wants_json else 1.2
        result = publish_articles_to_facebook_bulk(clean_ids, delay_seconds=delay_seconds)
        if wants_json:
            self.respond_json(result)
            return

        self.redirect(
            self.admin_return_url_from_fields(
                fields,
                default_status="approved",
                notice=summarize_facebook_bulk_result(result),
            )
        )

    def handle_article_action(self, path):
        match = re.fullmatch(r"/admin/articles/(\d+)/(approve|reject|delete|restore)", path)
        if not match:
            self.respond_html(render_not_found(), HTTPStatus.NOT_FOUND)
            return
        article_id = int(match.group(1))
        action = match.group(2)
        status_map = {
            "approve": "approved",
            "reject": "rejected",
            "delete": "deleted",
            "restore": "pending",
        }
        set_article_status(article_id, status_map[action])
        target_status = "pending" if action == "restore" else status_map[action]
        notice = auto_send_telegram_notice_background([article_id]) if action == "approve" else ""
        self.redirect(admin_filter_url(target_status, notice=notice))

    def handle_article_export(self, path):
        match = re.fullmatch(r"/admin/articles/(\d+)/export\.png", path)
        if not match:
            self.respond_html(render_not_found(), HTTPStatus.NOT_FOUND)
            return

        article_id = int(match.group(1))
        article = get_article(article_id)
        target = resolve_article_export_image(article)
        if not target:
            self.respond_html(render_not_found(), HTTPStatus.NOT_FOUND)
            return

        output = io.BytesIO()
        try:
            with Image.open(target) as image:
                image.save(output, format="PNG")
        except Exception as exc:
            LOGGER.warning("Khong export duoc PNG cho bai #%s: %s", article_id, exc)
            self.respond_html(render_not_found(), HTTPStatus.NOT_FOUND)
            return

        payload = output.getvalue()
        filename = f"pnews-{article_id}-{slugify(article['title'])}.png"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def handle_chat_api(self):
        try:
            payload = json.loads(self.read_body().decode("utf-8", errors="replace") or "{}")
        except json.JSONDecodeError:
            self.respond_json(
                {
                    "answer": "Tin nhắn không hợp lệ. Bạn hãy thử nhập lại câu hỏi nhé.",
                    "articles": [],
                    "mode": "rule",
                    "provider": "none",
                },
                HTTPStatus.BAD_REQUEST,
            )
            return

        message = str(payload.get("message", "")).strip()
        if len(message) > 500:
            message = message[:500]

        try:
            response = handle_chat_message(message)
        except Exception as exc:
            LOGGER.warning("Chat API error: %s", exc)
            response = {
                "answer": "Tôi chưa xử lý được câu hỏi này lúc này. Bạn có thể thử hỏi tin mới nhất hoặc chọn một chủ đề cụ thể hơn.",
                "articles": [],
                "mode": "fallback",
                "provider": "none",
            }
        self.respond_json(serialize_chat_response(response))

    def public_articles_json(self, query):
        q = (query.get("q") or [""])[0].strip()
        topic = (query.get("topic") or [""])[0].strip()
        source = (query.get("source") or [""])[0].strip()
        rows = query_articles(status="approved", q=q, topic=topic, source=source)
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "summary": row["summary"],
                "source": row["source"],
                "category": row["category"],
                "content_topic": row["content_topic"],
                "image": article_image_url(row),
                "url": row["url"],
                "published_at": row["published_at"] or row["reviewed_at"] or row["updated_at"],
                "approved_at": row["approved_at"] or row["reviewed_at"],
                "deleted_at": row["deleted_at"],
            }
            for row in rows
        ]

    def read_body(self):
        content_length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(content_length)

    def read_form(self):
        content_type = self.headers.get("Content-Type", "")
        body = self.read_body()
        if content_type.startswith("application/x-www-form-urlencoded"):
            return parse_form_urlencoded(body)
        if content_type.startswith("multipart/form-data"):
            fields, _ = parse_multipart(body, content_type)
            return fields
        return {}

    def read_form_multi(self):
        content_type = self.headers.get("Content-Type", "")
        body = self.read_body()
        if content_type.startswith("application/x-www-form-urlencoded"):
            return parse_form_urlencoded_multi(body)
        if content_type.startswith("multipart/form-data"):
            fields, _ = parse_multipart(body, content_type)
            return {key: [value] for key, value in fields.items()}
        return {}

    def request_wants_json(self):
        content_type = self.headers.get("Content-Type", "")
        accept = self.headers.get("Accept", "")
        return content_type.startswith("application/json") or "application/json" in accept

    def read_json_payload(self):
        try:
            return json.loads(self.read_body().decode("utf-8", errors="replace") or "{}")
        except json.JSONDecodeError:
            self.respond_json(
                {
                    "success": False,
                    "message": "Payload JSON khong hop le.",
                    "error": "Invalid JSON body.",
                },
                HTTPStatus.BAD_REQUEST,
            )
            return None

    def admin_return_url_from_fields(self, fields, default_status="approved", notice=""):
        fields = fields or {}
        return_status = (fields.get("return_status") or [default_status])[0]
        return_q = (fields.get("return_q") or [""])[0].strip()
        return_source = (fields.get("return_source") or [""])[0].strip()
        return_topic = (fields.get("return_topic") or [""])[0].strip()
        return_date_raw = (fields.get("return_date") or [today_iso_date()])[0].strip()
        return_date = "" if return_date_raw == "all" else return_date_raw
        return_page = (fields.get("return_page") or ["1"])[0].strip()
        return admin_filter_url(
            return_status or default_status,
            return_q,
            return_source,
            return_topic,
            date_filter=return_date,
            notice=notice,
            page=return_page,
        )

    def is_authenticated(self):
        return self.get_session_id() in SESSIONS

    def get_session_id(self):
        cookie_header = self.headers.get("Cookie", "")
        cookie = SimpleCookie(cookie_header)
        if SESSION_COOKIE not in cookie:
            return ""
        return cookie[SESSION_COOKIE].value

    def clear_admin_session(self):
        session_id = self.get_session_id()
        if session_id in SESSIONS:
            SESSIONS.remove(session_id)

    def should_clear_admin_session(self):
        path = urlparse(self.path).path
        return path == "/client" or path.startswith("/client/article/")

    def send_clear_session_cookie(self):
        self.clear_admin_session()
        self.send_header("Set-Cookie", f"{SESSION_COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax")

    def require_admin(self, callback):
        if not self.is_authenticated():
            self.redirect("/admin")
            return
        callback()

    def should_no_cache(self):
        path = urlparse(self.path).path
        return path.startswith("/admin") or path in {"/dashboard"} or self.should_clear_admin_session()

    def send_no_cache_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")

    def redirect(self, location):
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        if str(location or "").startswith("/client"):
            self.send_clear_session_cookie()
        if (
            self.should_no_cache()
            or str(location or "").startswith("/admin")
            or str(location or "").startswith("/client")
        ):
            self.send_no_cache_headers()
        self.end_headers()

    def respond_html(self, body, status=HTTPStatus.OK):
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        if self.should_clear_admin_session():
            self.send_clear_session_cookie()
        if self.should_no_cache():
            self.send_no_cache_headers()
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def respond_json(self, data, status=HTTPStatus.OK):
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if self.should_no_cache():
            self.send_no_cache_headers()
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def serve_asset(self, relative_path):
        self.serve_file(ASSET_DIR, relative_path)

    def serve_media(self, relative_path):
        self.serve_file(BASE_DIR, unquote(relative_path))

    def serve_file(self, root, relative_path):
        target = (root / relative_path).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = guess_content_type(target)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(target.stat().st_size))
        self.end_headers()
        with target.open("rb") as file:
            shutil.copyfileobj(file, self.wfile)

    def log_message(self, format, *args):
        LOGGER.info("%s", format % args)


def guess_content_type(path):
    suffix = path.suffix.lower()
    return {
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".json": "application/json; charset=utf-8",
    }.get(suffix, "application/octet-stream")


def run(host="127.0.0.1", port=8000):
    # Đảm bảo các thư mục cần thiết được tự động tạo khi chạy
    ensure_runtime_dirs()

    init_db()
    server = ThreadingHTTPServer((host, port), CMSHandler)
    LOGGER.info(f"PNews CMS running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run PNews CMS web app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    run(args.host, args.port)
