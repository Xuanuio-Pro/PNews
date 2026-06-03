import csv
import hashlib
import json
import re
import sys
import time
import unicodedata
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont

try:
    from slugify import slugify as py_slugify
except Exception:  # pragma: no cover - optional dependency
    py_slugify = None


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"

CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1350

THUMBNAIL_X = 0
THUMBNAIL_Y = 0
THUMBNAIL_W = 1080
THUMBNAIL_H = 610

CONTENT_X = 0
CONTENT_Y = 610
CONTENT_W = 1080
CONTENT_H = 740

PADDING_X = 56
CONTENT_BG = (234, 242, 248)  # #EAF2F8

TITLE_X = 56
TITLE_Y = 700
TITLE_MAX_WIDTH = 968
TITLE_MAX_LINES = 3
TITLE_FONT_SIZE = 64
TITLE_LINE_SPACING = 12

SUMMARY_X = 56
SUMMARY_MAX_WIDTH = 968
SUMMARY_MAX_LINES = 5
SUMMARY_FONT_SIZE = 40
SUMMARY_LINE_SPACING = 10
SUMMARY_TOP_GAP = 55

SOURCE_FONT_SIZE = 32
SOURCE_RIGHT_PADDING = 56
SOURCE_BOTTOM_PADDING = 50

LOGO_TEXT = "PNews"
LOGO_MARGIN_TOP = 24
LOGO_MARGIN_RIGHT = 26
LOGO_FONT_SIZE = 48
LOGO_PADDING_X = 22
LOGO_PADDING_Y = 12

DEFAULT_PLACEHOLDER_IMAGE = "PNews.png"
THUMBNAIL_CACHE_DIR = DATA_DIR / "thumbnails"
ARTICLE_IMAGE_CACHE_PATH = THUMBNAIL_CACHE_DIR / "article_images.json"
DEFAULT_OUTPUT_DIR = DATA_DIR / "generated_images"

REQUEST_TIMEOUT_SECONDS = 9
JPEG_QUALITY = 92
THUMBNAIL_OVERLAY_ALPHA = 28

TEXT_DARK = (8, 20, 40)
TEXT_SUMMARY = (10, 28, 52)
TEXT_SOURCE = (64, 79, 98)

IMAGE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    )
}

image_session = requests.Session()
image_session.headers.update(IMAGE_HEADERS)
article_image_cache = None
_fallback_image_cache_path = None


def safe_print(message):
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        safe_message = str(message).encode(encoding, errors="replace").decode(encoding)
        print(safe_message)


def download_image(url):
    """Load image from HTTP URL or local path and return Pillow RGB image."""
    value = str(url or "").strip()
    if not value:
        return None

    try:
        local_path = _resolve_local_path(value)
        if local_path and local_path.exists() and local_path.is_file():
            return Image.open(local_path).convert("RGB")

        if not _is_http_url(value):
            return None

        image_bytes = _get_cached_or_downloaded_image(value)
        image = Image.open(BytesIO(image_bytes))
        return image.convert("RGB")
    except Exception as exc:
        safe_print(f"[WARN] Khong tai duoc thumbnail '{value}': {exc}")
        return None


def resize_and_crop(image, target_width, target_height):
    """Cover + center crop without distorting source image."""
    source_width, source_height = image.size
    if source_width <= 0 or source_height <= 0:
        return Image.new("RGB", (target_width, target_height), (0, 0, 0))

    source_ratio = source_width / source_height
    target_ratio = target_width / target_height

    if source_ratio >= target_ratio:
        resize_height = target_height
        resize_width = int(round(resize_height * source_ratio))
    else:
        resize_width = target_width
        resize_height = int(round(resize_width / source_ratio))

    resized = image.resize((resize_width, resize_height), Image.Resampling.LANCZOS)

    left = max((resize_width - target_width) // 2, 0)
    top = max((resize_height - target_height) // 2, 0)
    right = left + target_width
    bottom = top + target_height
    return resized.crop((left, top, right, bottom))


def wrap_text(text, font, max_width, draw):
    """Backward-compatible wrapper without max-lines clipping."""
    return wrap_text_by_width(
        draw=draw,
        text=text,
        font=font,
        max_width=max_width,
        max_lines=1000,
    )


def wrap_text_by_width(draw, text, font, max_width, max_lines):
    """Wrap text by measured pixel width and clip with ellipsis when needed."""
    raw = _clean_display_text(text)
    if not raw:
        return []

    lines = _wrap_text_unlimited(draw, raw, font, max_width)
    if len(lines) <= max_lines:
        return lines

    clipped = lines[:max_lines]
    clipped[-1] = _truncate_with_ellipsis(draw, clipped[-1], font, max_width)
    return clipped


def generate_news_card(article: dict, output_dir: str = "data/generated_images") -> str:
    """Generate one card and return created image path as string."""
    output_path, _, _ = generate_news_card_with_status(article, output_dir=output_dir)
    return output_path


def generate_news_card_with_status(article: dict, output_dir: str = "data/generated_images"):
    """Generate one card and return (path, used_fallback, thumbnail_source)."""
    output_root = _resolve_output_dir(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    prepared = prepare_article_for_card(article)
    output_name = _build_output_filename(prepared, index=None)
    output_path = _unique_output_path(output_root / output_name)
    created, used_fallback, thumbnail_source = _render_and_save_card(
        prepared,
        output_path,
        brand_name=LOGO_TEXT,
    )
    return str(created), used_fallback, thumbnail_source


def create_news_card(article, output_path, brand_name="PNews"):
    """Create social news card using existing public interface."""
    output = _resolve_output_path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    prepared = prepare_article_for_card(article)
    _render_and_save_card(prepared, output, brand_name=brand_name or LOGO_TEXT)
    return output


def prepare_article_for_card(article):
    """Normalize article fields while preserving original schema."""
    data = dict(article or {})

    title = _clean_display_text(data.get("title"))
    if not title:
        title = "Tin tức PNews"

    source = _clean_display_text(data.get("source"))
    if not source:
        source = "PNews"

    category = _clean_display_text(data.get("category"))
    content_topic = _clean_display_text(data.get("content_topic"))
    if not category:
        category = content_topic

    summary = _clean_display_text(data.get("summary"))
    if not summary:
        summary = _best_summary(data)
    summary = _clean_display_text(summary) or "Nội dung đang được cập nhật."

    data["title"] = title
    data["source"] = source
    data["category"] = category
    data["content_topic"] = content_topic
    data["summary"] = summary
    data["source_label"] = _build_source_label(source, category, content_topic)
    return data


def create_news_cards_from_json(json_path, output_dir, limit=None, brand_name="PNews"):
    """Create news cards from a JSON file containing article list."""
    output_root = _resolve_output_dir(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    with _resolve_local_path(str(json_path)).open("r", encoding="utf-8") as file:
        articles = json.load(file)

    if limit is not None:
        articles = articles[:limit]

    output_paths = []
    for index, article in enumerate(articles, start=1):
        prepared = prepare_article_for_card(article)
        name = _build_output_filename(prepared, index=index)
        output_path = _unique_output_path(output_root / name)
        created = create_news_card(prepared, output_path, brand_name=brand_name)
        output_paths.append(created)

    return output_paths


def load_articles_from_csv(csv_path):
    with _resolve_local_path(str(csv_path)).open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def create_news_cards_from_csv(
    csv_path,
    output_dir,
    limit=None,
    brand_name="PNews",
    require_thumbnail=False,
):
    """Create news cards from exported CSV."""
    articles = load_articles_from_csv(csv_path)

    if require_thumbnail:
        articles = [
            article
            for article in articles
            if _is_http_url(article.get("thumbnail", ""))
        ]

    if limit is not None:
        articles = articles[:limit]

    output_root = _resolve_output_dir(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    output_paths = []

    for index, article in enumerate(articles, start=1):
        prepared = prepare_article_for_card(article)
        name = _build_output_filename(prepared, index=index)
        output_path = _unique_output_path(output_root / name)
        created = create_news_card(prepared, output_path, brand_name=brand_name)
        output_paths.append(created)

    return output_paths


def _render_and_save_card(article, output_path, brand_name):
    canvas, used_fallback, thumbnail_source = _render_news_card_image(article, brand_name)

    output = _resolve_output_path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    save_image = canvas.convert("RGB")
    if output.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        output = output.with_suffix(".jpg")

    if output.suffix.lower() in {".jpg", ".jpeg"}:
        save_image.save(output, quality=JPEG_QUALITY, optimize=True)
    else:
        save_image.save(output)

    mode = "fallback" if used_fallback else "thumbnail"
    safe_print(f"[INFO] {mode} | {thumbnail_source} | {article.get('title', '')}")
    safe_print(f"[OK] Da tao news card: {output}")
    return output, used_fallback, thumbnail_source


def _render_news_card_image(article, brand_name):
    canvas = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (255, 255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    thumbnail, used_fallback, thumbnail_source = _load_best_thumbnail(article)
    thumbnail = resize_and_crop(thumbnail, THUMBNAIL_W, THUMBNAIL_H).convert("RGBA")
    canvas.paste(thumbnail, (THUMBNAIL_X, THUMBNAIL_Y))

    dark_overlay = Image.new("RGBA", (THUMBNAIL_W, THUMBNAIL_H), (0, 0, 0, THUMBNAIL_OVERLAY_ALPHA))
    canvas.alpha_composite(dark_overlay, (THUMBNAIL_X, THUMBNAIL_Y))

    draw.rectangle(
        (
            CONTENT_X,
            CONTENT_Y,
            CONTENT_X + CONTENT_W,
            CONTENT_Y + CONTENT_H,
        ),
        fill=CONTENT_BG + (255,),
    )

    _draw_logo(canvas, brand_name or LOGO_TEXT)
    _draw_content(draw, article)
    return canvas, used_fallback, thumbnail_source


def _draw_logo(canvas, brand_text):
    draw = ImageDraw.Draw(canvas)
    font = _load_bold_font(LOGO_FONT_SIZE)

    text = _clean_display_text(brand_text) or LOGO_TEXT
    left, top, right, bottom = _text_bbox(draw, text, font)
    text_w = right - left
    text_h = bottom - top
    box_w = text_w + (LOGO_PADDING_X * 2)
    box_h = text_h + (LOGO_PADDING_Y * 2)

    box_right = CANVAS_WIDTH - LOGO_MARGIN_RIGHT
    box_left = box_right - box_w
    box_top = LOGO_MARGIN_TOP
    box_bottom = box_top + box_h

    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rounded_rectangle(
        (box_left, box_top, box_right, box_bottom),
        radius=10,
        fill=(0, 0, 0, 190),
    )
    canvas.alpha_composite(overlay)

    draw = ImageDraw.Draw(canvas)
    text_x = box_left + LOGO_PADDING_X
    text_y = box_top + LOGO_PADDING_Y - top
    _draw_text(draw, (text_x, text_y), text, font, (255, 255, 255))


def _draw_content(draw, article):
    title_font = _load_bold_font(TITLE_FONT_SIZE)
    summary_font = _load_regular_font(SUMMARY_FONT_SIZE)
    source_font = _load_regular_font(SOURCE_FONT_SIZE)

    title_lines = wrap_text_by_width(
        draw=draw,
        text=article.get("title", ""),
        font=title_font,
        max_width=TITLE_MAX_WIDTH,
        max_lines=TITLE_MAX_LINES,
    )

    y = TITLE_Y
    title_line_h = _line_height(draw, title_font) + TITLE_LINE_SPACING
    for line in title_lines:
        _draw_text(draw, (TITLE_X, y), line, title_font, TEXT_DARK)
        y += title_line_h

    title_bottom = y if title_lines else TITLE_Y
    summary_y = title_bottom + SUMMARY_TOP_GAP

    source_text = _build_source_label(
        article.get("source", ""),
        article.get("category", ""),
        article.get("content_topic", ""),
    )
    source_text = _clean_display_text(source_text) or "PNews"
    source_text = _truncate_with_ellipsis(
        draw,
        source_text,
        source_font,
        CANVAS_WIDTH - (PADDING_X * 2),
        force_suffix=False,
    )

    source_w = _text_width(draw, source_text, source_font)
    source_x = CANVAS_WIDTH - SOURCE_RIGHT_PADDING - source_w
    source_line_h = _line_height(draw, source_font)
    source_y = CANVAS_HEIGHT - SOURCE_BOTTOM_PADDING - source_line_h

    summary_line_h = _line_height(draw, summary_font) + SUMMARY_LINE_SPACING
    available_summary_h = max(source_y - summary_y - 24, summary_line_h)
    max_lines_by_height = max(1, available_summary_h // summary_line_h)
    summary_max_lines = min(SUMMARY_MAX_LINES, max_lines_by_height)

    summary_lines = wrap_text_by_width(
        draw=draw,
        text=article.get("summary", ""),
        font=summary_font,
        max_width=SUMMARY_MAX_WIDTH,
        max_lines=summary_max_lines,
    )

    y = summary_y
    for line in summary_lines:
        _draw_text(draw, (SUMMARY_X, y), line, summary_font, TEXT_SUMMARY)
        y += summary_line_h

    _draw_text(draw, (source_x, source_y), source_text, source_font, TEXT_SOURCE)


def _build_source_label(source, category, content_topic):
    source_text = _clean_display_text(source) or "PNews"
    category_text = _clean_display_text(category)
    topic_text = _clean_display_text(content_topic)

    if category_text:
        return f"{source_text} - {category_text}"
    if topic_text:
        return f"{source_text} - {topic_text}"
    return source_text


def _best_summary(article):
    summary = _clean_display_text(article.get("summary", ""))
    if summary:
        return _trim_for_card(summary)

    content_summary = _summary_from_article_url(article)
    if content_summary:
        return _trim_for_card(content_summary)

    return "Nội dung đang được cập nhật."


def _summary_from_article_url(article):
    article_url = str(article.get("url", "")).strip()
    if not _is_http_url(article_url):
        return ""

    try:
        response = image_session.get(article_url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.encoding = response.apparent_encoding or "utf-8"
        response.raise_for_status()
    except requests.RequestException:
        return ""

    soup = BeautifulSoup(response.text, "lxml")
    for selector in ("script", "style", "noscript", "iframe"):
        for tag in soup.select(selector):
            tag.decompose()

    for meta_summary in _meta_contents(soup, "meta[name='description'], meta[property='og:description']"):
        if _useful_card_summary(meta_summary, article.get("title", "")):
            return meta_summary

    scopes = [
        scope
        for selector in (
            "article.fck_detail",
            ".fck_detail",
            ".entry-content",
            ".post-content",
            ".detail-content",
            ".article-content",
            "article",
            "main",
        )
        for scope in soup.select(selector)
    ] or [soup]

    paragraphs = []
    for scope in scopes:
        paragraphs = [
            _clean_display_text(paragraph.get_text(" ", strip=True))
            for paragraph in scope.select("p")
        ]
        paragraphs = [
            paragraph
            for paragraph in paragraphs
            if _useful_card_summary(paragraph, article.get("title", ""))
        ]
        if paragraphs:
            break

    return " ".join(paragraphs[:2]).strip()


def _meta_contents(soup, selector):
    return [
        _clean_display_text(tag.get("content", ""))
        for tag in soup.select(selector)
        if tag.get("content")
    ]


def _useful_card_summary(summary, title):
    text = _clean_display_text(summary)
    if len(text) < 40:
        return False
    normalized = text.lower()
    ignored = ("xem chi tiet", "doc them", "tin lien quan", "theo doi", "trang chu")
    return normalized != _clean_display_text(title).lower() and not any(token in normalized for token in ignored)


def _trim_for_card(summary, max_length=320):
    text = _clean_display_text(summary)
    if len(text) <= max_length:
        return text
    trimmed = text[:max_length].rsplit(" ", 1)[0].rstrip(" ,.;:")
    return f"{trimmed}…"


def _load_best_thumbnail(article):
    for candidate in _thumbnail_candidates(article):
        image = download_image(candidate)
        if image is not None:
            return image, False, candidate

    fallback = _load_fallback_image(article)
    return fallback, True, "fallback:PNews"


def _thumbnail_candidates(article):
    candidates = []
    for key in ("thumbnail", "image_url", "cover_image", "local_image", "uploaded_image"):
        value = str(article.get(key, "") or "").strip()
        if not value:
            continue
        candidates.extend(_image_url_variants(value))

    # Fast path: when direct thumbnail candidates already exist, skip fetching
    # article HTML for og:image to avoid extra network latency per article.
    if candidates:
        return _dedupe(candidates)

    article_url = str(article.get("url", "") or "").strip()
    if _is_http_url(article_url):
        article_image = _extract_article_image_url(article_url)
        if article_image:
            candidates.insert(0, article_image)

    return _dedupe(candidates)


def _extract_article_image_url(article_url):
    cached_url = _get_cached_article_image_url(article_url)
    if cached_url:
        return cached_url

    try:
        response = image_session.get(article_url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException:
        return ""

    soup = BeautifulSoup(response.text, "lxml")
    selectors = [
        'meta[property="og:image"]',
        'meta[property="og:image:secure_url"]',
        'meta[name="twitter:image"]',
    ]
    for selector in selectors:
        tag = soup.select_one(selector)
        content = tag.get("content", "").strip() if tag else ""
        if content:
            image_url = urljoin(article_url, content)
            _cache_article_image_url(article_url, image_url)
            return image_url

    content_image = _extract_content_image_url(soup, article_url)
    if content_image:
        _cache_article_image_url(article_url, content_image)
        return content_image

    return ""


def _extract_content_image_url(soup, article_url):
    image_attrs = (
        "data-src",
        "data-original",
        "data-lazy-src",
        "data-thumb",
        "data-image",
        "src",
        "data-srcset",
        "srcset",
    )
    selectors = [
        ".entry-content",
        ".post-content",
        ".single-post-content",
        ".article-content",
        "article",
    ]
    scopes = [scope for selector in selectors for scope in soup.select(selector)] or [soup]

    for scope in scopes:
        for img in scope.select("img"):
            for attr in image_attrs:
                value = img.get(attr) or ""
                if not value:
                    continue
                if "srcset" in attr:
                    value = value.split(",")[0].strip().split(" ")[0]
                if value.startswith("data:"):
                    continue
                image_url = urljoin(article_url, value)
                if _looks_like_content_image(image_url):
                    return image_url
    return ""


def _looks_like_content_image(url):
    normalized = (url or "").lower()
    blocked = ("logo", "icon", "avatar", "facebook", "youtube", "sprite")
    return not any(token in normalized for token in blocked)


def _get_cached_article_image_url(article_url):
    cache = _load_article_image_cache()
    return cache.get(article_url, "")


def _cache_article_image_url(article_url, image_url):
    cache = _load_article_image_cache()
    cache[article_url] = image_url
    ARTICLE_IMAGE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ARTICLE_IMAGE_CACHE_PATH.open("w", encoding="utf-8") as file:
        json.dump(cache, file, ensure_ascii=False, indent=2)


def _load_article_image_cache():
    global article_image_cache
    if article_image_cache is not None:
        return article_image_cache

    if not ARTICLE_IMAGE_CACHE_PATH.exists():
        article_image_cache = {}
        return article_image_cache

    try:
        with ARTICLE_IMAGE_CACHE_PATH.open("r", encoding="utf-8") as file:
            article_image_cache = json.load(file)
    except (OSError, json.JSONDecodeError):
        article_image_cache = {}
    return article_image_cache


def _load_fallback_image(article=None):
    fallback_path = _resolve_fallback_image_path()
    if fallback_path and fallback_path.exists():
        try:
            return Image.open(fallback_path).convert("RGB")
        except Exception as exc:
            safe_print(f"[WARN] Khong mo duoc fallback image '{fallback_path}': {exc}")

    safe_print("[WARN] Khong tim thay anh fallback PNews. Tao placeholder tam.")
    return _create_placeholder_thumbnail(article)


def _create_placeholder_thumbnail(article=None):
    source = _clean_display_text((article or {}).get("source") or "PNews")
    category = _clean_display_text(
        (article or {}).get("category") or (article or {}).get("content_topic") or ""
    )
    image = Image.new("RGB", (THUMBNAIL_W, THUMBNAIL_H), (14, 42, 82))
    draw = ImageDraw.Draw(image)
    brand_font = _load_bold_font(72)
    meta_font = _load_regular_font(36)
    _draw_text(draw, (PADDING_X, 220), LOGO_TEXT, brand_font, (245, 245, 245))
    meta = " - ".join(value for value in (source, category) if value)
    if meta:
        _draw_text(draw, (PADDING_X, 320), meta, meta_font, (214, 225, 240))
    return image


def _resolve_fallback_image_path():
    global _fallback_image_cache_path
    if _fallback_image_cache_path is not None:
        return _fallback_image_cache_path

    direct_candidates = [
        BASE_DIR / DEFAULT_PLACEHOLDER_IMAGE,
        BASE_DIR / "PNews.jpg",
        BASE_DIR / "PNews.jpeg",
        BASE_DIR / "PNews.webp",
        DATA_DIR / DEFAULT_PLACEHOLDER_IMAGE,
    ]
    for path in direct_candidates:
        if path.exists() and path.is_file():
            _fallback_image_cache_path = path
            return path

    glob_candidates = []
    for pattern in ("*PNews*.png", "*PNews*.jpg", "*PNews*.jpeg", "*PNews*.webp"):
        glob_candidates.extend(BASE_DIR.glob(pattern))
    glob_candidates = sorted([path for path in glob_candidates if path.is_file()])

    _fallback_image_cache_path = glob_candidates[0] if glob_candidates else None
    return _fallback_image_cache_path


def _image_url_variants(url):
    if not _is_http_url(url):
        return [url]

    variants = [url]
    stripped = _strip_query(url)
    if stripped != url:
        variants.insert(0, stripped)

    upgraded = _upgrade_thumbnail_url(url)
    if upgraded != url:
        variants.insert(0, upgraded)
    return variants


def _strip_query(url):
    parsed = urlparse(url)
    return urlunparse(parsed._replace(query=""))


def _upgrade_thumbnail_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return url

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if "w" in query or "h" in query:
        query["w"] = str(THUMBNAIL_W)
        query["h"] = str(THUMBNAIL_H)
        query["q"] = "100"
        query["dpr"] = "1"
        query.setdefault("fit", "crop")

    return urlunparse(parsed._replace(query=urlencode(query)))


def _fetch_image_response(url):
    upgraded = _upgrade_thumbnail_url(url)
    urls = [upgraded]
    if upgraded != url:
        urls.append(url)

    last_error = None
    for candidate in urls:
        try:
            response = image_session.get(candidate, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
    raise last_error


def _get_cached_or_downloaded_image(url):
    cache_path = _thumbnail_cache_path(url)
    if cache_path.exists():
        return cache_path.read_bytes()

    response = _fetch_image_response(url)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(response.content)
    return response.content


def _thumbnail_cache_path(url):
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return THUMBNAIL_CACHE_DIR / f"{digest}{suffix}"


def _load_font(font_path, size, fallback_paths=None):
    candidates = [font_path]
    candidates.extend(fallback_paths or [])

    for candidate in candidates:
        if not candidate:
            continue
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue

    safe_print(
        "[WARN] Khong tim thay font TTF ho tro tieng Viet. "
        "Dung ImageFont.load_default() (co the loi dau tieng Viet)."
    )
    return ImageFont.load_default()


def _load_bold_font(size):
    candidates = _bold_font_candidates()
    return _load_font(candidates[0], size, candidates[1:])


def _load_regular_font(size):
    candidates = _regular_font_candidates()
    return _load_font(candidates[0], size, candidates[1:])


def _bold_font_candidates():
    return [
        str(BASE_DIR / "assets" / "fonts" / "DejaVuSans-Bold.ttf"),
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]


def _regular_font_candidates():
    return [
        str(BASE_DIR / "assets" / "fonts" / "DejaVuSans.ttf"),
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]


def _text_bbox(draw, text, font):
    return draw.textbbox((0, 0), str(text or ""), font=font)


def _text_width(draw, text, font):
    left, _, right, _ = _text_bbox(draw, text, font)
    return right - left


def _line_height(draw, font, sample_text="Ag"):
    _, top, _, bottom = _text_bbox(draw, sample_text, font)
    return bottom - top


def _draw_text(draw, position, text, font, fill):
    draw.text(position, str(text or ""), font=font, fill=fill)


def _wrap_text_unlimited(draw, text, font, max_width):
    paragraphs = [part.strip() for part in re.split(r"[\r\n]+", str(text or "")) if part.strip()]
    if not paragraphs:
        return []

    lines = []
    for paragraph in paragraphs:
        current = ""
        words = paragraph.split(" ")

        for word in words:
            if not word:
                continue

            test_line = word if not current else f"{current} {word}"
            if _text_width(draw, test_line, font) <= max_width:
                current = test_line
                continue

            if current:
                lines.append(current)
                current = ""

            if _text_width(draw, word, font) <= max_width:
                current = word
                continue

            split_parts = _split_long_word(draw, word, font, max_width)
            if split_parts:
                lines.extend(split_parts[:-1])
                current = split_parts[-1]

        if current:
            lines.append(current)

    return lines


def _split_long_word(draw, word, font, max_width):
    if _text_width(draw, word, font) <= max_width:
        return [word]

    parts = []
    current = ""
    for char in word:
        test = f"{current}{char}"
        if current and _text_width(draw, test, font) > max_width:
            parts.append(current)
            current = char
        else:
            current = test
    if current:
        parts.append(current)
    return parts


def _truncate_with_ellipsis(draw, text, font, max_width, force_suffix=True):
    ellipsis = "…"
    clean = str(text or "").rstrip()
    if not clean:
        return ellipsis if force_suffix else ""

    if not force_suffix and _text_width(draw, clean, font) <= max_width:
        return clean

    if _text_width(draw, f"{clean}{ellipsis}", font) <= max_width:
        return f"{clean}{ellipsis}"

    while clean:
        clean = clean[:-1].rstrip()
        if _text_width(draw, f"{clean}{ellipsis}", font) <= max_width:
            return f"{clean}{ellipsis}"
    return ellipsis


def _clean_display_text(value):
    return " ".join(str(value or "").split())


def _is_http_url(value):
    parsed = urlparse(str(value or ""))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _dedupe(values):
    output = []
    seen = set()
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            output.append(item)
            seen.add(item)
    return output


def _resolve_local_path(value):
    path = Path(str(value or "").strip())
    if path.is_absolute():
        return path
    return BASE_DIR / path


def _resolve_output_dir(output_dir):
    path = Path(str(output_dir or "").strip() or str(DEFAULT_OUTPUT_DIR))
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def _resolve_output_path(output_path):
    path = Path(str(output_path or "").strip())
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def _build_output_filename(article, index=None):
    title_slug = _slugify_text(article.get("title", ""))
    if not title_slug:
        url_digest = hashlib.sha1(str(article.get("url", "")).encode("utf-8")).hexdigest()[:10]
        title_slug = f"article-{url_digest or int(time.time())}"

    source_slug = _slugify_text(article.get("source", "")) or "pnews"
    category_slug = _slugify_text(article.get("category") or article.get("content_topic") or "") or "news"

    if index is None:
        stem = f"{source_slug}-{category_slug}-{title_slug}"
    else:
        stem = f"{index:03d}-{source_slug}-{category_slug}-{title_slug}"

    stem = stem[:180].strip("-")
    if not stem:
        stem = f"article-{int(time.time())}"
    return f"{stem}.jpg"


def _slugify_text(value):
    raw = str(value or "").strip()
    if not raw:
        return ""

    if py_slugify is not None:
        try:
            slug = py_slugify(raw, separator="-")
            slug = re.sub(r"[^a-zA-Z0-9-]+", "", slug.lower()).strip("-")
            if slug:
                return slug[:100]
        except Exception:
            pass

    normalized = unicodedata.normalize("NFKD", raw.replace("Đ", "D").replace("đ", "d"))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:100]


def _unique_output_path(path):
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    for index in range(2, 10000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}-{int(time.time())}{suffix}")


if __name__ == "__main__":
    sample_article = {
        "source": "VNExpress",
        "title": "Dai hoc danh tieng My xoa so quy tac tram nam vi gian lan",
        "url": "https://vnexpress.net/example.html",
        "crawled_at": "2026-05-27 07:00:00",
        "published_at": "2026-05-27 06:30:00",
        "thumbnail": "Mau.jpg",
        "summary": "Noi dung dang duoc cap nhat.",
        "summary_source": "crawler",
        "newspaper_type": "Bao dien tu",
        "content_topic": "Giao duc",
        "category": "Giao duc",
    }

    output = generate_news_card(sample_article, "data/generated_images")
    safe_print(f"Generated: {output}")
