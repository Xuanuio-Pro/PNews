import json
import re
import unicodedata
import csv
import hashlib
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont


CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1350
THUMBNAIL_HEIGHT = 620
PADDING_X = 56
CARD_BACKGROUND = (226, 238, 247)
TEXT_BLACK = (4, 8, 14)
SHADOW_BLACK = (24, 24, 24)
FOOTER_GRAY = (50, 59, 73)
WHITE = (245, 245, 245)

DEFAULT_BOLD_FONT = "templates/fonts/BeVietnamPro-Bold.ttf"
DEFAULT_REGULAR_FONT = "templates/fonts/BeVietnamPro-Regular.ttf"
DEFAULT_PLACEHOLDER_IMAGE = "IEC News.png"
THUMBNAIL_CACHE_DIR = "data/thumbnails"
ARTICLE_IMAGE_CACHE_PATH = Path(THUMBNAIL_CACHE_DIR) / "article_images.json"
MIN_ACCEPTABLE_THUMBNAIL_WIDTH = 700
MIN_ACCEPTABLE_THUMBNAIL_HEIGHT = 380

IMAGE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    )
}

image_session = requests.Session()
image_session.headers.update(IMAGE_HEADERS)
article_image_cache = None


def download_image(url):
    """Download an image from URL and return a Pillow RGB image.

    The input can be an HTTP URL or a local image path. Returns None if input is
    empty, invalid, blocked, or not an image.
    """
    if not url:
        return None

    try:
        if Path(url).exists():
            return Image.open(url).convert("RGB")

        image_bytes = _get_cached_or_downloaded_image(url)

        image = Image.open(BytesIO(image_bytes))
        return image.convert("RGB")
    except Exception as exc:
        print(f"[WARN] Không tải được thumbnail từ {url}: {exc}")
        return None


def resize_and_crop(image, target_width, target_height):
    """Resize image using fill crop so it keeps aspect ratio.

    Landscape thumbnails are center-cropped. Very tall images are cropped from
    the top so a reference card or portrait image does not pull lower text into
    the thumbnail area.
    """
    source_width, source_height = image.size
    source_ratio = source_width / source_height
    target_ratio = target_width / target_height

    if source_ratio > target_ratio:
        resize_height = target_height
        resize_width = int(target_height * source_ratio)
    else:
        resize_width = target_width
        resize_height = int(target_width / source_ratio)

    resized = image.resize((resize_width, resize_height), Image.Resampling.LANCZOS)

    left = (resize_width - target_width) // 2
    if source_ratio < target_ratio:
        top = 0
    else:
        top = (resize_height - target_height) // 2
    right = left + target_width
    bottom = top + target_height

    return resized.crop((left, top, right, bottom))


def wrap_text(text, font, max_width, draw):
    """Wrap text into lines that fit max_width."""
    words = str(text or "").split()
    lines = []
    current_line = ""

    for word in words:
        word_parts = _split_long_word(word, font, max_width, draw)

        for word_part in word_parts:
            test_line = word_part if not current_line else f"{current_line} {word_part}"

            if _text_width(draw, test_line, font) <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word_part

    if current_line:
        lines.append(current_line)

    return lines


def _split_long_word(word, font, max_width, draw):
    if _text_width(draw, word, font) <= max_width:
        return [word]

    parts = []
    current_part = ""

    for char in word:
        test_part = f"{current_part}{char}"

        if current_part and _text_width(draw, test_part, font) > max_width:
            parts.append(current_part)
            current_part = char
        else:
            current_part = test_part

    if current_part:
        parts.append(current_part)

    return parts


def create_news_card(article, output_path, brand_name="IEC News"):
    """Create a 1080x1350 social news card from one article dictionary."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    canvas = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), CARD_BACKGROUND)
    draw = ImageDraw.Draw(canvas)

    thumbnail = _load_best_thumbnail(article)
    if thumbnail is None:
        thumbnail = _create_placeholder_thumbnail()

    thumbnail = resize_and_crop(thumbnail, CANVAS_WIDTH, THUMBNAIL_HEIGHT)
    canvas.paste(thumbnail, (0, 0))

    _draw_brand(canvas, brand_name)
    draw = ImageDraw.Draw(canvas)
    _draw_text_content(draw, article)

    if output.suffix.lower() in {".jpg", ".jpeg"}:
        canvas.save(output, quality=95, optimize=True)
    else:
        canvas.save(output)

    print(f"[OK] Đã tạo news card: {output}")
    return output


def create_news_cards_from_json(json_path, output_dir, limit=None, brand_name="IEC News"):
    """Create news cards from a JSON file containing a list of articles."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with Path(json_path).open("r", encoding="utf-8") as file:
        articles = json.load(file)

    if limit is not None:
        articles = articles[:limit]

    output_paths = []

    for index, article in enumerate(articles, start=1):
        title_slug = _slugify(article.get("title", f"article-{index}"))
        output_path = output_dir / f"{index:03d}-{title_slug}.jpg"
        output_paths.append(create_news_card(article, output_path, brand_name))

    return output_paths


def load_articles_from_csv(csv_path):
    """Load articles from a UTF-8/UTF-8-SIG CSV export."""
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def create_news_cards_from_csv(
    csv_path,
    output_dir,
    limit=None,
    brand_name="IEC News",
    require_thumbnail=False,
):
    """Create news cards from exported articles CSV.

    Articles without thumbnail URLs use DEFAULT_PLACEHOLDER_IMAGE.
    """
    articles = load_articles_from_csv(csv_path)

    if require_thumbnail:
        articles = [
            article for article in articles
            if _is_http_url(article.get("thumbnail", ""))
        ]

    if limit is not None:
        articles = articles[:limit]

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = []

    for index, article in enumerate(articles, start=1):
        source_slug = _slugify(article.get("source", "source"))
        category_slug = _slugify(article.get("category", "category"))
        title_slug = _slugify(article.get("title", f"article-{index}"))
        filename = f"{index:03d}-{source_slug}-{category_slug}-{title_slug}.jpg"
        output_path = output_dir / filename
        output_paths.append(create_news_card(article, output_path, brand_name))

    return output_paths


def _load_font(font_path, size, fallback_paths=None):
    """Load TrueType font with Windows-friendly fallbacks.

    Project fonts are preferred. If they do not exist, the code tries common
    Windows fonts that support Vietnamese. The final fallback is Pillow's
    default font, which may not render Vietnamese accents as well as TTF fonts.
    """
    candidates = [font_path]
    candidates.extend(fallback_paths or [])

    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)

    print(f"[WARN] Không tìm thấy font {font_path}. Dùng font mặc định của Pillow.")
    return ImageFont.load_default()


def _text_bbox(draw, text, font):
    try:
        return draw.textbbox((0, 0), text, font=font)
    except UnicodeEncodeError:
        safe_text = text.encode("latin-1", "replace").decode("latin-1")
        return draw.textbbox((0, 0), safe_text, font=font)


def _text_width(draw, text, font):
    left, _, right, _ = _text_bbox(draw, text, font)
    return right - left


def _line_height(draw, font, sample_text="Ag"):
    _, top, _, bottom = _text_bbox(draw, sample_text, font)
    return bottom - top


def _draw_text(draw, position, text, font, fill, stroke_width=0, stroke_fill=None):
    try:
        draw.text(
            position,
            text,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill or fill,
        )
    except UnicodeEncodeError:
        safe_text = text.encode("latin-1", "replace").decode("latin-1")
        draw.text(
            position,
            safe_text,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill or fill,
        )


def _truncate_lines(lines, max_lines, draw, font, max_width):
    if len(lines) <= max_lines:
        return lines

    truncated = lines[:max_lines]
    last_line = truncated[-1]
    ellipsis = "..."

    while last_line and _text_width(draw, f"{last_line}{ellipsis}", font) > max_width:
        last_line = last_line[:-1].rstrip()

    truncated[-1] = f"{last_line}{ellipsis}" if last_line else ellipsis
    return truncated


def _create_placeholder_thumbnail():
    if Path(DEFAULT_PLACEHOLDER_IMAGE).exists():
        return Image.open(DEFAULT_PLACEHOLDER_IMAGE).convert("RGB")

    image = Image.new("RGB", (CANVAS_WIDTH, THUMBNAIL_HEIGHT), (20, 42, 74))
    draw = ImageDraw.Draw(image)
    font = _load_font(DEFAULT_BOLD_FONT, 54, _windows_bold_fonts())
    text = "IEC News"
    text_width = _text_width(draw, text, font)
    _draw_text(
        draw,
        ((CANVAS_WIDTH - text_width) // 2, THUMBNAIL_HEIGHT // 2 - 30),
        text,
        font,
        WHITE,
    )
    return image


def _slugify(value):
    value = (value or "article").replace("Đ", "D").replace("đ", "d")
    normalized = unicodedata.normalize("NFKD", value or "article")
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_value = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value.lower()).strip("-")
    return ascii_value[:80] or "article"


def _is_http_url(value):
    parsed = urlparse(value or "")
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _load_best_thumbnail(article):
    best_image = None
    best_score = 0

    for image_url in _thumbnail_candidates(article):
        image = download_image(image_url)

        if image is None:
            continue

        width, height = image.size
        score = width * height

        if score > best_score:
            best_image = image
            best_score = score

        if width >= CANVAS_WIDTH and height >= THUMBNAIL_HEIGHT:
            return image

    if best_image is not None:
        width, height = best_image.size

        if width >= MIN_ACCEPTABLE_THUMBNAIL_WIDTH and height >= MIN_ACCEPTABLE_THUMBNAIL_HEIGHT:
            return best_image

    if Path(DEFAULT_PLACEHOLDER_IMAGE).exists():
        return Image.open(DEFAULT_PLACEHOLDER_IMAGE).convert("RGB")

    return None


def _thumbnail_candidates(article):
    candidates = []
    article_url = article.get("url", "")
    thumbnail_url = article.get("thumbnail", "")

    if _is_http_url(article_url):
        article_image = _extract_article_image_url(article_url)
        if article_image:
            candidates.append(article_image)

    if thumbnail_url:
        candidates.extend(_image_url_variants(thumbnail_url))

    return _dedupe(candidates)


def _extract_article_image_url(article_url):
    cached_url = _get_cached_article_image_url(article_url)

    if cached_url:
        return cached_url

    try:
        response = image_session.get(article_url, timeout=15)
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
        content = tag.get("content", "") if tag else ""

        if content:
            _cache_article_image_url(article_url, content)
            return content

    return ""


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
    except (json.JSONDecodeError, OSError):
        article_image_cache = {}

    return article_image_cache


def _image_url_variants(url):
    variants = [url]
    stripped_url = _strip_query(url)

    if stripped_url != url:
        variants.insert(0, stripped_url)

    upgraded_url = _upgrade_thumbnail_url(url)

    if upgraded_url != url:
        variants.insert(0, upgraded_url)

    return variants


def _strip_query(url):
    parsed = urlparse(url)
    return urlunparse(parsed._replace(query=""))


def _dedupe(values):
    result = []
    seen = set()

    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)

    return result


def _upgrade_thumbnail_url(url):
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        return url

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))

    if "w" in query or "h" in query:
        query["w"] = str(CANVAS_WIDTH)
        query["h"] = str(THUMBNAIL_HEIGHT)
        query["q"] = "100"
        query["dpr"] = "1"
        query.setdefault("fit", "crop")

    return urlunparse(parsed._replace(query=urlencode(query)))


def _fetch_image_response(url):
    upgraded_url = _upgrade_thumbnail_url(url)
    urls = [upgraded_url]

    if upgraded_url != url:
        urls.append(url)

    last_error = None

    for candidate_url in urls:
        try:
            response = image_session.get(candidate_url, timeout=15)
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
    return Path(THUMBNAIL_CACHE_DIR) / f"{digest}{suffix}"


def _clean_display_text(value):
    text = " ".join(str(value or "").split())
    return _fix_leading_location_spacing(text)


def _fix_leading_location_spacing(text):
    locations = [
        "An Giang", "Bà Rịa - Vũng Tàu", "Bắc Giang", "Bắc Ninh", "Bình Dương",
        "Bình Định", "Bình Thuận", "Cần Thơ", "Đà Nẵng", "Đắk Lắk",
        "Đồng Nai", "Đồng Tháp", "Hà Nội", "Hải Phòng", "Khánh Hòa",
        "Lâm Đồng", "Long An", "Nghệ An", "Quảng Nam", "Quảng Ninh",
        "Thanh Hóa", "TP HCM", "Vĩnh Long",
    ]

    for location in locations:
        if text.startswith(location) and len(text) > len(location):
            next_char = text[len(location)]
            if not next_char.isspace() and next_char.isupper():
                return f"{location} {text[len(location):]}"

    return text


def _draw_brand(canvas, brand_name):
    draw = ImageDraw.Draw(canvas)
    font = _load_font(DEFAULT_BOLD_FONT, 48, _windows_bold_fonts())
    margin_x = 28
    margin_y = 24
    brand_padding_x = 20
    brand_padding_y = 12
    text_width = _text_width(draw, brand_name, font)
    _, text_top, _, text_bottom = _text_bbox(draw, brand_name, font)
    text_height = text_bottom - text_top

    box_right = CANVAS_WIDTH - margin_x
    box_top = margin_y
    box_left = box_right - text_width - (brand_padding_x * 2)
    box_bottom = box_top + text_height + (brand_padding_y * 2)
    x = box_left + brand_padding_x
    y = box_top + brand_padding_y - text_top

    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle(
        (box_left, box_top, box_right, box_bottom),
        fill=(0, 0, 0, 190),
    )
    canvas.paste(Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB"), (0, 0))
    draw = ImageDraw.Draw(canvas)

    _draw_text(draw, (x + 2, y + 2), brand_name, font, SHADOW_BLACK)
    _draw_text(
        draw,
        (x, y),
        brand_name,
        font,
        (238, 240, 244),
        stroke_width=1,
        stroke_fill=(238, 240, 244),
    )


def _draw_text_content(draw, article):
    title_font = _load_font(DEFAULT_BOLD_FONT, 72, _windows_bold_fonts())
    summary_font = _load_font(DEFAULT_REGULAR_FONT, 43, _windows_regular_fonts())
    footer_font = _load_font(DEFAULT_REGULAR_FONT, 30, _windows_regular_fonts())

    max_text_width = CANVAS_WIDTH - (PADDING_X * 2)
    title = _clean_display_text(article.get("title", ""))
    summary = _clean_display_text(article.get("summary", ""))
    source = article.get("source", "")
    category = article.get("category", "")

    title_lines = wrap_text(title, title_font, max_text_width, draw)
    title_lines = _truncate_lines(title_lines, 3, draw, title_font, max_text_width)

    summary_lines = wrap_text(summary, summary_font, max_text_width, draw)
    summary_lines = _truncate_lines(summary_lines, 4, draw, summary_font, max_text_width)

    y = THUMBNAIL_HEIGHT + 70
    title_line_height = _line_height(draw, title_font, "Ág") + 18

    for line in title_lines:
        _draw_text(
            draw,
            (PADDING_X, y),
            line,
            title_font,
            TEXT_BLACK,
            stroke_width=1,
            stroke_fill=TEXT_BLACK,
        )
        y += title_line_height

    y += 34
    summary_line_height = _line_height(draw, summary_font, "Ág") + 18

    for line in summary_lines:
        _draw_text(
            draw,
            (PADDING_X, y),
            line,
            summary_font,
            TEXT_BLACK,
        )
        y += summary_line_height

    footer = " - ".join(value for value in [source, category] if value)
    footer_width = _text_width(draw, footer, footer_font)
    footer_x = CANVAS_WIDTH - PADDING_X - footer_width
    footer_y = CANVAS_HEIGHT - 72
    _draw_text(draw, (footer_x, footer_y), footer, footer_font, FOOTER_GRAY)


def _windows_bold_fonts():
    return [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
    ]


def _windows_regular_fonts():
    return [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ]


if __name__ == "__main__":
    sample_article = {
        "source": "vnexpress.net",
        "title": "Giá vàng được dự báo giảm tiếp tuần sau",
        "url": "https://example.com/article",
        "crawled_at": "2026-05-19T07:00:00",
        "thumbnail": "Mẫu.jpg",
        "summary": (
            "Nhiều nhà phân tích Phố Wall dự báo giá vàng thế giới giảm trong "
            "tuần tới do chịu sức ép từ giá dầu và rủi ro thắt chặt tiền tệ."
        ),
        "newspaper_type": "Báo điện tử",
        "content_topic": "Kinh doanh",
        "category": "Kinh doanh",
    }

    create_news_card(
        sample_article,
        "data/generated_images/sample_news_card.jpg",
    )
