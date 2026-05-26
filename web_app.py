import csv
import hashlib
import html
import json
import os
import re
import secrets
import shutil
import sqlite3
import unicodedata
from datetime import datetime
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from services.article_search import find_rendered_image
from services.chatbot_service import CHAT_SUGGESTIONS, handle_chat_message, init_chat_logs
from services.notification_service import NotificationService


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "cms.sqlite3"
UPLOAD_DIR = DATA_DIR / "uploads"
ASSET_DIR = BASE_DIR / "web_assets"

ADMIN_USERNAME = os.environ.get("IEC_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("IEC_ADMIN_PASSWORD", "admin123")
SESSION_COOKIE = "iec_cms_session"
SESSIONS = set()

ARTICLE_COLUMNS = [
    "source",
    "title",
    "url",
    "crawled_at",
    "thumbnail",
    "summary",
    "summary_source",
    "newspaper_type",
    "content_topic",
    "category",
]

STATUS_LABELS = {
    "pending": "Chờ duyệt",
    "approved": "Đã đăng",
    "rejected": "Từ chối",
    "deleted": "Đã xóa",
}

ALLOWED_UPLOAD_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def slugify(value):
    value = str(value or "bài viết").replace("Đ", "D").replace("đ", "d")
    normalized = unicodedata.normalize("NFKD", value.lower())
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized or "bai-viet"


def escape(value):
    return html.escape(str(value or ""), quote=True)


def connect_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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
                thumbnail TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                summary_source TEXT DEFAULT '',
                newspaper_type TEXT DEFAULT '',
                content_topic TEXT DEFAULT '',
                category TEXT DEFAULT '',
                image_path TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                reviewed_at TEXT DEFAULT '',
                deleted_at TEXT DEFAULT ''
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_url ON articles(url) WHERE url != ''")
        conn.commit()
    init_chat_logs()
    seed_articles_from_csv()


def seed_articles_from_csv():
    csv_path = DATA_DIR / "exports" / "articles.csv"
    if not csv_path.exists():
        return

    generated_images = find_generated_images()

    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    with connect_db() as conn:
        existing_urls = {
            row["url"]
            for row in conn.execute("SELECT url FROM articles WHERE url != ''")
        }
        for row in rows:
            url = row.get("url", "").strip()
            title = row.get("title", "").strip()
            if not title or (url and url in existing_urls):
                continue

            image_path = match_generated_image(title, generated_images)
            values = {column: row.get(column, "") for column in ARTICLE_COLUMNS}
            values["image_path"] = image_path
            values["created_at"] = now_iso()
            values["updated_at"] = values["created_at"]
            conn.execute(
                """
                INSERT INTO articles (
                    source, title, url, crawled_at, thumbnail, summary,
                    summary_source, newspaper_type, content_topic, category,
                    image_path, created_at, updated_at
                ) VALUES (
                    :source, :title, :url, :crawled_at, :thumbnail, :summary,
                    :summary_source, :newspaper_type, :content_topic, :category,
                    :image_path, :created_at, :updated_at
                )
                """,
                values,
            )
            if url:
                existing_urls.add(url)
        conn.commit()


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


def query_articles(status=None, q=None, topic=None, source=None, limit=None):
    where = []
    params = {}

    if status:
        where.append("status = :status")
        params["status"] = status

    if q:
        where.append("(title LIKE :q OR summary LIKE :q OR source LIKE :q)")
        params["q"] = f"%{q}%"

    if topic:
        where.append("(content_topic = :topic OR category = :topic)")
        params["topic"] = topic

    if source:
        where.append("source = :source")
        params["source"] = source

    sql = "SELECT * FROM articles"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += """
    ORDER BY
      date(COALESCE(NULLIF(crawled_at, ''), created_at)) DESC,
      datetime(COALESCE(NULLIF(crawled_at, ''), created_at)) DESC,
      id DESC
    """
    if limit:
        sql += " LIMIT :limit"
        params["limit"] = limit

    with connect_db() as conn:
        return conn.execute(sql, params).fetchall()


def get_article(article_id):
    with connect_db() as conn:
        return conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()


def set_article_status(article_id, status):
    reviewed_at = now_iso() if status in {"approved", "rejected"} else ""
    deleted_at = now_iso() if status == "deleted" else ""
    with connect_db() as conn:
        conn.execute(
            """
            UPDATE articles
            SET status = ?, reviewed_at = ?, deleted_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, reviewed_at, deleted_at, now_iso(), article_id),
        )
        conn.commit()


def set_articles_status(article_ids, status):
    ids = [int(article_id) for article_id in article_ids if str(article_id).isdigit()]
    if not ids:
        return 0

    reviewed_at = now_iso() if status in {"approved", "rejected"} else ""
    deleted_at = now_iso() if status == "deleted" else ""
    placeholders = ",".join("?" for _ in ids)
    params = [status, reviewed_at, deleted_at, now_iso(), *ids]

    with connect_db() as conn:
        cursor = conn.execute(
            f"""
            UPDATE articles
            SET status = ?, reviewed_at = ?, deleted_at = ?, updated_at = ?
            WHERE id IN ({placeholders})
            """,
            params,
        )
        conn.commit()
        return cursor.rowcount


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
                source, title, url, crawled_at, thumbnail, summary,
                newspaper_type, content_topic, category, image_path,
                status, created_at, updated_at, reviewed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fields.get("source", "Admin upload").strip() or "Admin upload",
                title,
                fields.get("url", "").strip(),
                timestamp,
                "",
                fields.get("summary", "").strip(),
                fields.get("newspaper_type", "").strip(),
                fields.get("content_topic", "").strip(),
                fields.get("category", "").strip(),
                image_path,
                status,
                timestamp,
                timestamp,
                timestamp if status == "approved" else "",
            ),
        )
        conn.commit()


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
    topic_expr = (
        "COALESCE(NULLIF(TRIM(content_topic), ''), NULLIF(TRIM(category), ''), '')"
        if {"content_topic", "category"}.issubset(columns)
        else sql_value_expr(columns, "content_topic", sql_value_expr(columns, "category"))
    )
    order_parts = []
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
            latest_crawled_at = ""
            if "crawled_at" in columns:
                row = conn.execute(
                    "SELECT MAX(NULLIF(crawled_at, '')) AS latest FROM articles"
                ).fetchone()
                latest_crawled_at = row["latest"] or ""
            warnings = get_data_quality_warnings(conn, columns, source_counts)

            cards = [
                {"label": "Tổng số bài viết", "value": total, "tone": "blue"},
                {"label": "Đã đăng / approved", "value": status_counts["published"], "tone": "green"},
                {"label": "Chờ duyệt / pending", "value": status_counts["pending"], "tone": "amber"},
                {"label": "Bị từ chối / rejected", "value": status_counts["rejected"], "tone": "red"},
            ]
            if "status" in columns:
                cards.append({"label": "Đã xóa / deleted", "value": status_counts["deleted"], "tone": "muted"})
            cards.extend([
                {"label": "Thiếu summary", "value": warnings["missing_summary"], "tone": "amber"},
                {"label": "Thiếu thumbnail", "value": warnings["missing_thumbnail"], "tone": "amber"},
                {"label": "Nguồn báo có dữ liệu", "value": len(source_counts), "tone": "blue"},
                {"label": "Crawl gần nhất", "value": latest_crawled_at or "Chưa có", "tone": "muted", "wide": True},
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
    return make_media_url(article["image_path"] or article["thumbnail"])


def render_select_options(items, selected_value, empty_label):
    options = [f'<option value="">{escape(empty_label)}</option>']
    for item in items:
        selected = "selected" if item == selected_value else ""
        options.append(f'<option value="{escape(item)}" {selected}>{escape(item)}</option>')
    return "".join(options)


def render_client_page(title, body, extra_class=""):
    return f"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} - IEC News</title>
  <link rel="stylesheet" href="/assets/styles.css">
  <script src="/assets/app.js" defer></script>
</head>
<body class="client-app {escape(extra_class)}">
  <header class="client-topbar">
    <a class="brand" href="/client">
      <span class="brand-mark">IEC</span>
      <span>
        <strong>IEC News</strong>
        <small>Ấn phẩm đã được biên tập duyệt</small>
      </span>
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


def render_admin_page(title, body, extra_class="", active_nav="articles"):
    dashboard_active = "active" if active_nav == "dashboard" else ""
    articles_active = "active" if active_nav == "articles" else ""
    upload_active = "active" if active_nav == "upload" else ""
    return f"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} - Quản trị IEC News</title>
  <link rel="stylesheet" href="/assets/styles.css">
  <script src="/assets/app.js" defer></script>
</head>
<body class="admin-app {escape(extra_class)}">
  <aside class="admin-sidebar">
    <a class="brand admin-brand" href="/admin">
      <span class="brand-mark">IEC</span>
      <span>
        <strong>Quản trị tin</strong>
        <small>Kiểm duyệt và xuất bản</small>
      </span>
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
  {render_scroll_top_button()}
</body>
</html>"""


def render_auth_page(title, body):
    return f"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} - Quản trị IEC News</title>
  <link rel="stylesheet" href="/assets/styles.css">
  <script src="/assets/app.js" defer></script>
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
      <strong>Hỏi IEC News</strong>
    </button>
    <div class="chatbot-panel" data-chat-panel aria-hidden="true">
      <header class="chatbot-head">
        <div>
          <strong>IEC News Assistant</strong>
          <span>Hỏi nhanh tin tức mới nhất</span>
        </div>
        <button class="chatbot-close" type="button" data-chat-close aria-label="Đóng chat">×</button>
      </header>
      <div class="chatbot-messages" data-chat-messages>
        <article class="chat-message bot">
          <p>Xin chào, tôi có thể giúp bạn tìm tin mới, tin theo chủ đề, nguồn báo hoặc tóm tắt các bài đã đăng trên IEC News.</p>
        </article>
      </div>
      <div class="chatbot-suggestions" data-chat-suggestions>{chips}</div>
      <form class="chatbot-form" data-chat-form>
        <input name="message" maxlength="500" autocomplete="off" placeholder="Nhập câu hỏi về tin tức..." required>
        <button class="button primary compact" type="submit">Gửi</button>
      </form>
    </div>
  </section>"""


def render_client_home(query):
    q = (query.get("q") or [""])[0].strip()
    topic = (query.get("topic") or [""])[0].strip()
    source = (query.get("source") or [""])[0].strip()
    articles = query_articles(status="approved", q=q, topic=topic, source=source)
    topics = get_topics()
    sources = get_sources(status="approved")
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

    body = f"""
    <section class="client-hero">
      <div>
        <p class="eyebrow">Client demo</p>
        <h1>Ấn phẩm đã duyệt</h1>
        <p class="hero-copy">Không gian xem trước các bài đã được admin chọn xuất bản. Luồng này có thể nối tiếp sang tự động đăng bài, chatbot hoặc thông báo Zalo về sau.</p>
      </div>
    </section>
    <section class="client-filter-panel">
      <form class="filter-bar client-filter" method="get" action="/client">
        <input type="search" name="q" placeholder="Tìm tiêu đề, tóm tắt, nguồn..." value="{escape(q)}">
        <select name="source" aria-label="Lọc theo tờ báo">{source_options}</select>
        <select name="topic">{topic_options}</select>
        <button class="button primary" type="submit">Lọc bài</button>
      </form>
    </section>
    <section class="article-grid">{cards}</section>
    """
    return render_client_page("Client", body)


def render_client_card(article):
    image_url = article_image_url(article)
    image = (
        f'<img src="{escape(image_url)}" alt="{escape(article["title"])}" loading="lazy">'
        if image_url
        else '<div class="image-fallback">IEC News</div>'
    )
    return f"""
    <article class="article-card">
      <a class="article-image" href="/client/article/{article['id']}">{image}</a>
      <div class="article-body">
        <div class="meta-line">
          <span>{escape(article['source'] or 'IEC')}</span>
          <span>{escape(article['category'] or article['content_topic'] or 'Tin mới')}</span>
        </div>
        <h2><a href="/client/article/{article['id']}">{escape(article['title'])}</a></h2>
        <p>{escape(article['summary'] or 'Bài viết đã được duyệt và sẵn sàng hiển thị trên trang client.')}</p>
        <a class="text-link" href="/client/article/{article['id']}">Xem chi tiết</a>
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
        else '<div class="image-fallback detail">IEC News</div>'
    )
    source_link = (
        f'<a class="button ghost" href="{escape(article["url"])}" target="_blank" rel="noopener">Mở bài gốc</a>'
        if article["url"]
        else ""
    )
    body = f"""
    <article class="detail-layout">
      <div class="detail-media">{image}</div>
      <div class="detail-content">
        <a class="text-link" href="/client">Quay lại client</a>
        <div class="meta-line">
          <span>{escape(article['source'])}</span>
          <span>{escape(article['content_topic'] or article['category'])}</span>
        </div>
        <h1>{escape(article['title'])}</h1>
        <p class="detail-summary">{escape(article['summary'] or 'Bài viết đã được duyệt và sẵn sàng hiển thị trên trang client.')}</p>
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
        <p class="eyebrow">Admin</p>
        <h1>Đăng nhập duyệt bài</h1>
        <p>Mặc định: user <code>admin</code>, mật khẩu <code>admin123</code>. Có thể đổi bằng biến môi trường <code>IEC_ADMIN_USER</code> và <code>IEC_ADMIN_PASSWORD</code>.</p>
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


def render_admin_overview_dashboard():
    stats = get_admin_dashboard_stats()
    if not stats["ready"]:
        body = f"""
        <section class="admin-head">
          <div>
            <p class="eyebrow">Dashboard</p>
            <h1>Tổng quan IEC News</h1>
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

    cards = "\n".join(
        f"""
        <article class="dashboard-card tone-{escape(card['tone'])} {'wide' if card.get('wide') else ''}">
          <span>{escape(card['label'])}</span>
          <strong>{escape(card['value'])}</strong>
        </article>
        """
        for card in stats["cards"]
    )
    source_rows = render_dashboard_metric_rows(stats["source_counts"], "Chưa có nguồn báo nào.")
    topic_rows = render_dashboard_metric_rows(stats["topic_counts"], "Chưa có dữ liệu chủ đề.")
    recent_rows = render_dashboard_recent_articles(stats["recent_articles"])
    warning_rows = render_dashboard_warnings(stats["warnings"]["items"])
    status_rows = render_dashboard_status_rows(stats["raw_status_counts"])

    body = f"""
    <section class="admin-head">
      <div>
        <p class="eyebrow">Dashboard</p>
        <h1>Tổng quan IEC News</h1>
        <p>Theo dõi nhanh tình trạng dữ liệu tin tức, nguồn báo, chủ đề, trạng thái duyệt và hoạt động crawl.</p>
      </div>
      <div class="admin-actions">
        <a class="button primary" href="/admin">Duyệt bài</a>
        <a class="button ghost" href="/admin/upload">Tải ấn phẩm</a>
      </div>
    </section>
    <section class="dashboard-grid">{cards}</section>
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
        <span>{escape(stats["latest_crawled_at"] or "Chưa có crawled_at")}</span>
      </div>
      <div class="dashboard-table-wrap">
        <table class="dashboard-table">
          <thead>
            <tr>
              <th>Tiêu đề</th>
              <th>Nguồn</th>
              <th>Chủ đề</th>
              <th>Trạng thái</th>
              <th>Crawled at</th>
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
              <td>{escape(article.get('crawled_at') or 'Chưa có')}</td>
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
    thumbnail = (
        article.get("image_path")
        or find_rendered_image(article.get("title", ""))
        or article.get("thumbnail")
        or ""
    )
    return {
        "title": article.get("title", ""),
        "summary": article.get("summary", ""),
        "source": article.get("source", ""),
        "category": article.get("category", ""),
        "content_topic": article.get("content_topic", ""),
        "url": article.get("url", ""),
        "thumbnail": make_media_url(thumbnail),
        "crawled_at": article.get("crawled_at", ""),
    }


def render_admin_dashboard(query):
    status = (query.get("status") or ["pending"])[0]
    if status not in STATUS_LABELS:
        status = "pending"
    q = (query.get("q") or [""])[0].strip()
    source = (query.get("source") or [""])[0].strip()
    topic = (query.get("topic") or [""])[0].strip()
    notice = (query.get("notice") or [""])[0].strip()
    counts = get_counts()
    articles = query_articles(status=status, q=q, source=source, topic=topic)
    sources = get_sources()
    topics = get_topics(status=None)
    source_options = render_select_options(sources, source, "Tất cả tờ báo")
    topic_options = render_select_options(topics, topic, "Tất cả chủ đề")

    tabs = "".join(
        f'<a class="status-tab {"active" if status == key else ""}" href="{admin_filter_url(key, q, source, topic)}">{label}<strong>{counts.get(key, 0)}</strong></a>'
        for key, label in STATUS_LABELS.items()
    )
    rows = "\n".join(render_admin_article(article) for article in articles)
    if not rows:
        rows = '<div class="empty-state compact"><h2>Không có bài trong mục này</h2><p>Thử đổi bộ lọc hoặc tải thêm ấn phẩm mới.</p></div>'

    bulk_actions = render_bulk_actions(status)
    notice_html = f'<p class="form-success">{escape(notice)}</p>' if notice else ""

    body = f"""
    <section class="admin-head">
      <div>
        <p class="eyebrow">Bảng điều khiển</p>
        <h1>Duyệt ấn phẩm</h1>
        <p>Chọn từng bài hoặc chọn nhiều bài cùng lúc để đưa sang client, từ chối hoặc xóa khỏi hàng đợi.</p>
      </div>
      <div class="admin-actions">
        <a class="button ghost" href="/admin/dashboard">Xem tổng quan</a>
        <a class="button primary" href="/admin/upload">Tải ấn phẩm</a>
      </div>
    </section>
    <section class="status-tabs">{tabs}</section>
    <form class="admin-search" method="get" action="/admin">
      <input type="hidden" name="status" value="{escape(status)}">
      <input type="search" name="q" placeholder="Tìm trong hàng đợi..." value="{escape(q)}">
      <select name="source" aria-label="Lọc theo tờ báo">{source_options}</select>
      <select name="topic" aria-label="Lọc theo chủ đề">{topic_options}</select>
      <button class="button ghost" type="submit">Tìm</button>
    </form>
    {notice_html}
    <form class="bulk-review-form" method="post" action="/admin/bulk">
      <input type="hidden" name="return_status" value="{escape(status)}">
      <input type="hidden" name="return_q" value="{escape(q)}">
      <input type="hidden" name="return_source" value="{escape(source)}">
      <input type="hidden" name="return_topic" value="{escape(topic)}">
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
    </form>
    """
    return render_admin_page("Admin", body)


def admin_filter_url(status, q="", source="", topic="", notice=""):
    parts = [f"status={quote(status)}"]
    if q:
        parts.append(f"q={quote(q)}")
    if source:
        parts.append(f"source={quote(source)}")
    if topic:
        parts.append(f"topic={quote(topic)}")
    if notice:
        parts.append(f"notice={quote(notice)}")
    return "/admin?" + "&".join(parts)


def render_bulk_actions(status):
    actions_by_status = {
        "pending": [
            ("approve", "Duyệt đã chọn", "success"),
            ("reject", "Từ chối đã chọn", "ghost"),
            ("delete", "Xóa đã chọn", "danger"),
            ("send_telegram", "Đẩy Telegram", "primary"),
        ],
        "approved": [
            ("send_telegram", "Đẩy Telegram", "primary"),
            ("reject", "Gỡ khỏi client", "ghost"),
            ("delete", "Xóa đã chọn", "danger"),
        ],
        "rejected": [
            ("approve", "Duyệt lại", "success"),
            ("delete", "Xóa đã chọn", "danger"),
            ("send_telegram", "Đẩy Telegram", "primary"),
        ],
        "deleted": [
            ("restore", "Khôi phục đã chọn", "ghost"),
            ("send_telegram", "Đẩy Telegram", "primary"),
        ],
    }
    buttons = []
    for action, label, variant in actions_by_status.get(status, []):
        confirm = ' data-confirm-bulk="Bạn chưa chọn bài nào."' if action else ""
        buttons.append(
            f'<button class="button {variant}" name="bulk_action" value="{action}" type="submit"{confirm}>{label}</button>'
        )
    return "".join(buttons)


def render_admin_article(article):
    image_url = article_image_url(article)
    image = (
        f'<img src="{escape(image_url)}" alt="{escape(article["title"])}" loading="lazy">'
        if image_url
        else '<div class="image-fallback admin">IEC</div>'
    )
    source_link = (
        f'<a class="text-link" href="{escape(article["url"])}" target="_blank" rel="noopener">Bài gốc</a>'
        if article["url"]
        else ""
    )

    approve = action_button(article["id"], "approve", "Duyệt", "success")
    reject = action_button(article["id"], "reject", "Từ chối", "ghost")
    delete = action_button(article["id"], "delete", "Xóa", "danger")
    restore = action_button(article["id"], "restore", "Khôi phục", "ghost")

    actions = {
        "pending": approve + reject + delete,
        "approved": reject + delete,
        "rejected": approve + delete,
        "deleted": restore,
    }.get(article["status"], approve + delete)

    return f"""
    <article class="review-item">
      <label class="review-check" title="Chọn bài này">
        <input type="checkbox" name="article_ids" value="{article['id']}" data-row-check>
      </label>
      <div class="review-image">{image}</div>
      <div class="review-content">
        <div class="meta-line">
          <span>{escape(article['source'] or 'Admin')}</span>
          <span>{escape(article['category'] or article['content_topic'] or 'Chưa phân loại')}</span>
          <span class="badge">{escape(STATUS_LABELS.get(article['status'], article['status']))}</span>
        </div>
        <h2>{escape(article['title'])}</h2>
        <p>{escape(article['summary'] or 'Bài này chưa có tóm tắt. Admin có thể duyệt để demo client hoặc bổ sung nội dung ở bước phát triển tiếp theo.')}</p>
        <div class="review-foot">
          {source_link}
          <span>Cập nhật: {escape(article['updated_at'])}</span>
        </div>
      </div>
      <div class="review-actions">{actions}</div>
    </article>
    """


def action_button(article_id, action, label, variant):
    return f"""
      <button class="button {variant}" name="single_action" value="{action}:{article_id}" type="submit">{escape(label)}</button>
    """


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
      <a class="button ghost" href="/admin">Về admin</a>
    </section>
    <form class="upload-form" method="post" action="/admin/upload" enctype="multipart/form-data">
      {error_html}
      {success_html}
      <label>Tiêu đề<input name="title" required placeholder="Nhập tiêu đề bài viết hoặc ấn phẩm"></label>
      <label>Tóm tắt<textarea name="summary" rows="4" placeholder="Nội dung ngắn hiển thị trên client"></textarea></label>
      <div class="form-grid">
        <label>Nguồn<input name="source" placeholder="IEC, VNExpress..."></label>
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
    server_version = "IECNewsCMS/1.0"

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/":
            self.redirect("/client")
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
        elif path.startswith("/admin/articles/"):
            self.require_admin(lambda: self.handle_article_action(path))
        elif path == "/api/chat":
            self.handle_chat_api()
        else:
            self.respond_html(render_not_found(), HTTPStatus.NOT_FOUND)

    def handle_login(self):
        fields = self.read_form()
        if (
            fields.get("username") == ADMIN_USERNAME
            and fields.get("password") == ADMIN_PASSWORD
        ):
            session_id = secrets.token_urlsafe(32)
            SESSIONS.add(session_id)
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/admin")
            self.send_header("Set-Cookie", f"{SESSION_COOKIE}={session_id}; HttpOnly; SameSite=Lax; Path=/")
            self.end_headers()
            return
        self.respond_html(render_admin_login("Sai thông tin đăng nhập."), HTTPStatus.UNAUTHORIZED)

    def handle_logout(self):
        session_id = self.get_session_id()
        if session_id in SESSIONS:
            SESSIONS.remove(session_id)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/admin")
        self.send_header("Set-Cookie", f"{SESSION_COOKIE}=; Max-Age=0; Path=/")
        self.end_headers()

    def handle_upload(self):
        try:
            content_type = self.headers.get("Content-Type", "")
            body = self.read_body()
            fields, files = parse_multipart(body, content_type)
            create_uploaded_article(fields, files.get("image"))
        except ValueError as exc:
            self.respond_html(render_upload_form(error=str(exc)), HTTPStatus.BAD_REQUEST)
            return
        self.respond_html(render_upload_form(success="Đã lưu ấn phẩm vào hệ thống."))

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

        single_action = (fields.get("single_action") or [""])[0]
        if single_action:
            action, _, raw_id = single_action.partition(":")
            article_ids = [raw_id]
        else:
            action = (fields.get("bulk_action") or [""])[0]
            article_ids = fields.get("article_ids", [])

        notice = ""
        if action == "send_telegram" and article_ids:
            try:
                result = NotificationService(DB_PATH).send_selected_articles_to_telegram(article_ids)
                notice = (
                    "Telegram: gửi thành công "
                    f"{result['sent']} bài, bỏ qua {result['skipped']} bài, lỗi {result['failed']} bài."
                )
            except Exception as exc:
                notice = f"Telegram: không gửi được bài đã chọn ({str(exc)[:180]})."
        elif action in status_map and article_ids:
            set_articles_status(article_ids, status_map[action])
            return_status = "pending" if action == "restore" else status_map[action]

        self.redirect(admin_filter_url(return_status, return_q, return_source, return_topic, notice))

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
        self.redirect(f"/admin?status={target_status}")

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
            print(f"[WARN] Chat API error: {exc}")
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
                "published_at": row["reviewed_at"] or row["updated_at"],
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

    def is_authenticated(self):
        return self.get_session_id() in SESSIONS

    def get_session_id(self):
        cookie_header = self.headers.get("Cookie", "")
        cookie = SimpleCookie(cookie_header)
        if SESSION_COOKIE not in cookie:
            return ""
        return cookie[SESSION_COOKIE].value

    def require_admin(self, callback):
        if not self.is_authenticated():
            self.redirect("/admin")
            return
        callback()

    def redirect(self, location):
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def respond_html(self, body, status=HTTPStatus.OK):
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def respond_json(self, data, status=HTTPStatus.OK):
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
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
        print("[%s] %s" % (now_iso(), format % args))


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
    init_db()
    server = ThreadingHTTPServer((host, port), CMSHandler)
    print(f"IEC News CMS running at http://{host}:{port}")
    # print(f"Admin mặc định: {ADMIN_USERNAME} / {ADMIN_PASSWORD}")
    server.serve_forever()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run IEC News CMS web app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    run(args.host, args.port)
