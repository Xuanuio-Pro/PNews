import re
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "data" / "cms.sqlite3"
APPROVED_STATUS_ALIASES = {
    "approved",
    "published",
    "publish",
    "public",
    "posted",
    "dang",
    "da dang",
    "duyet",
    "da duyet",
}


def connect_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_latest_articles(limit=5):
    return _query_public_articles(limit=limit)


def search_articles(keyword, limit=5):
    keyword = _clean_query(keyword)
    if not keyword:
        return get_latest_articles(limit)
    return _query_public_articles(search=keyword, limit=limit)


def get_articles_by_source(source, limit=5):
    source = _clean_query(source)
    if not source:
        return get_latest_articles(limit)
    return _query_public_articles(source=source, limit=limit)


def get_articles_by_topic(topic, limit=5):
    topic = _clean_query(topic)
    if not topic:
        return get_latest_articles(limit)
    return _query_public_articles(topic=topic, limit=limit)


def get_articles_for_chat_context(message, limit=12):
    message = _clean_query(message)
    hints = detect_article_hints(message)
    if hints["source"]:
        return get_articles_by_source(hints["source"], limit)
    if hints["topic"]:
        return get_articles_by_topic(hints["topic"], limit)
    if hints["keyword"]:
        return search_articles(hints["keyword"], limit)
    return get_latest_articles(limit)


def get_articles_today(limit=5, source="", topic="", keyword=""):
    articles = _query_public_articles(search=keyword, topic=topic, source=source, limit=5000)
    today = datetime.now().strftime("%Y-%m-%d")
    return [
        article
        for article in articles
        if str(article.get("crawled_at", "")).startswith(today)
    ][:limit]


def count_articles_today(source="", topic="", keyword=""):
    articles = _query_public_articles(search=keyword, topic=topic, source=source, limit=5000)
    today = datetime.now().strftime("%Y-%m-%d")
    return sum(
        1
        for article in articles
        if str(article.get("crawled_at", "")).startswith(today)
    )


def count_articles(source="", topic="", keyword=""):
    return len(_query_public_articles(search=keyword, topic=topic, source=source, limit=5000))


def detect_article_hints(message):
    normalized = normalize_text(message)
    source = ""
    topic = ""

    source_aliases = {
        "VNExpress": ("vnexpress", "vn express", "vnex"),
        "Báo Chính phủ": ("bao chinh phu", "chinh phu"),
        "PTIT": ("ptit", "hoc vien cong nghe buu chinh vien thong"),
    }
    for label, aliases in source_aliases.items():
        if any(_contains_alias(normalized, alias) for alias in aliases):
            source = label
            break

    topic_aliases = {
        "công nghệ": ("cong nghe", "ai", "tri tue nhan tao", "chatgpt", "phan mem", "iphone"),
        "kinh doanh": ("kinh doanh", "thi truong", "chung khoan", "bat dong san", "doanh nghiep", "gia vang"),
        "giáo dục": ("giao duc", "sinh vien", "hoc tap", "truong", "dai hoc", "thi tot nghiep"),
        "thể thao": ("the thao", "bong da", "world cup", "v league", "tennis"),
        "giải trí": ("giai tri", "dien anh", "am nhac", "nghe si"),
        "sức khỏe": ("suc khoe", "y te", "benh", "bac si"),
        "pháp luật": ("phap luat", "toa an", "cong an", "vu an"),
        "đời sống": ("doi song", "xa hoi", "gia dinh", "du lich"),
        "thời sự": ("thoi su", "chinh phu", "quoc hoi"),
    }
    for label, aliases in topic_aliases.items():
        if any(_contains_alias(normalized, alias) for alias in aliases):
            topic = label
            break

    keyword = ""
    keyword_match = re.search(
        r"(?:tim|bai ve|lien quan den|ve|chu de)\s+(.+)",
        normalized,
    )
    if keyword_match:
        keyword = _clean_keyword(keyword_match.group(1))
    elif not source and not topic:
        words = [word for word in normalized.split() if len(word) > 2]
        keyword = " ".join(words[:6])

    return {"source": source, "topic": topic, "keyword": keyword}


def _clean_keyword(value):
    ignored = {
        "khong",
        "nao",
        "moi",
        "nhat",
        "hom",
        "nay",
        "cho",
        "toi",
        "xem",
        "tin",
        "bai",
        "bao",
        "co",
        "tim",
        "ve",
    }
    words = [
        word
        for word in normalize_text(value).split()
        if word not in ignored and len(word) > 1
    ]
    return " ".join(words[:8])


def _query_public_articles(search="", topic="", source="", limit=5):
    if not DB_PATH.exists():
        return []

    try:
        with connect_db() as conn:
            if not _table_exists(conn, "articles"):
                return []
            columns = _get_columns(conn, "articles")
            rows = _fetch_public_rows(conn, columns, max(limit * 20, 250))
    except sqlite3.Error:
        return []

    filtered = []
    for row in rows:
        article = _article_from_row(row, columns)
        if source and not _matches(source, article["source"]):
            continue
        if topic and not (
            _matches(topic, article["content_topic"])
            or _matches(topic, article["category"])
            or _matches(topic, article["title"])
            or _matches(topic, article["summary"])
        ):
            continue
        if search and not _matches_any(search, article):
            continue
        filtered.append(article)
        if len(filtered) >= limit:
            break
    return filtered


def _fetch_public_rows(conn, columns, limit):
    select_columns = [
        column
        for column in [
            "id",
            "source",
            "title",
            "url",
            "thumbnail",
            "image_path",
            "summary",
            "crawled_at",
            "published_at",
            "newspaper_type",
            "content_topic",
            "category",
            "status",
            "created_at",
            "updated_at",
        ]
        if column in columns
    ]
    if not select_columns:
        return []

    where = []
    params = {}
    if "status" in columns:
        placeholders = ", ".join(f":status_{index}" for index, _ in enumerate(APPROVED_STATUS_ALIASES))
        for index, status in enumerate(APPROVED_STATUS_ALIASES):
            params[f"status_{index}"] = status
        where.append(f"LOWER(TRIM(status)) IN ({placeholders})")

    order_parts = []
    if "published_at" in columns:
        order_parts.append("datetime(NULLIF(published_at, '')) DESC")
        order_parts.append("NULLIF(published_at, '') DESC")
    if "crawled_at" in columns:
        order_parts.append("datetime(NULLIF(crawled_at, '')) DESC")
        order_parts.append("NULLIF(crawled_at, '') DESC")
    if "created_at" in columns:
        order_parts.append("datetime(NULLIF(created_at, '')) DESC")
    if "id" in columns:
        order_parts.append("id DESC")
    order_sql = ", ".join(order_parts) or "rowid DESC"

    sql = f"SELECT {', '.join(select_columns)} FROM articles"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {order_sql} LIMIT :limit"
    params["limit"] = limit
    return conn.execute(sql, params).fetchall()


def _article_from_row(row, columns):
    data = dict(row)
    rendered_image = data.get("image_path") or find_rendered_image(data.get("title", ""))
    thumbnail = rendered_image or data.get("thumbnail") or ""
    return {
        "id": data.get("id", ""),
        "title": data.get("title", ""),
        "summary": data.get("summary", ""),
        "source": data.get("source", ""),
        "category": data.get("category", ""),
        "content_topic": data.get("content_topic", ""),
        "url": data.get("url", ""),
        "thumbnail": thumbnail,
        "image_path": rendered_image,
        "published_at": data.get("published_at") or "",
        "crawled_at": data.get("published_at") or data.get("crawled_at") or data.get("created_at") or data.get("updated_at") or "",
        "status": data.get("status", ""),
    }


def _matches_any(keyword, article):
    haystack = " ".join(
        str(article.get(key, ""))
        for key in ["title", "summary", "source", "category", "content_topic"]
    )
    return _matches(keyword, haystack)


def find_rendered_image(title):
    title_slug = slugify(title)
    if not title_slug:
        return ""
    image_root = BASE_DIR / "data" / "generated_images"
    if not image_root.exists():
        return ""
    for extension in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
        for image_path in image_root.rglob(extension):
            if title_slug in image_path.stem:
                return str(image_path.relative_to(BASE_DIR)).replace("\\", "/")
    return ""


def slugify(value):
    value = str(value or "").replace("Đ", "D").replace("đ", "d")
    normalized = unicodedata.normalize("NFKD", value.lower())
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized


def _matches(needle, haystack):
    normalized_needle = normalize_text(needle)
    normalized_haystack = normalize_text(haystack)
    if not normalized_needle:
        return True
    if len(normalized_needle) <= 2:
        return re.search(rf"\b{re.escape(normalized_needle)}\b", normalized_haystack) is not None
    return normalized_needle in normalized_haystack


def _contains_alias(normalized_text, alias):
    alias = normalize_text(alias)
    if not alias:
        return False
    if len(alias) <= 2 or " " not in alias:
        return re.search(rf"\b{re.escape(alias)}\b", normalized_text) is not None
    return alias in normalized_text


def _clean_query(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:120]


def normalize_text(value):
    value = str(value or "").lower().replace("đ", "d")
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _table_exists(conn, table_name):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _get_columns(conn, table_name):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")}
