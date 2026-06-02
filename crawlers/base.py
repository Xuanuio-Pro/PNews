import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from time import sleep
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    )
}

REQUEST_TIMEOUT = 15
REQUEST_DELAY_SECONDS = 0.2

DATETIME_META_SELECTORS = [
    "meta[property='article:published_time']",
    "meta[property='og:published_time']",
    "meta[name='pubdate']",
    "meta[name='publishdate']",
    "meta[name='date']",
    "meta[itemprop='datePublished']",
]

DATETIME_TEXT_SELECTORS = [
    "time[datetime]",
    "time",
    ".time-public",
    ".date",
    ".post-date",
    ".entry-date",
    ".elementor-post-date",
    ".detail-time",
    ".article-date",
    ".news-date",
    ".publish-date",
]

session = requests.Session()
session.headers.update(HEADERS)


def get_html(url):
    try:
        sleep(REQUEST_DELAY_SECONDS)
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.encoding = response.apparent_encoding or "utf-8"
        response.raise_for_status()
        return response.text
    except requests.RequestException as exc:
        print(f"[ERROR] Không lấy được HTML từ {url}: {exc}")
        return None


def make_soup(url):
    html = get_html(url)

    if html is None:
        return None

    return BeautifulSoup(html, "lxml")


def clean_text(value):
    if value is None:
        return ""

    return " ".join(value.split())


def normalize_url(base_url, url):
    if not url:
        return ""

    return urljoin(base_url, url.strip())


def extract_image_url(block, base_url):
    image_attrs = (
        "data-src",
        "data-original",
        "data-lazy-src",
        "data-thumb",
        "data-image",
        "data-url",
        "src",
        "data-srcset",
        "srcset",
    )

    for img in block.select("img"):
        for attr in image_attrs:
            thumbnail = img.get(attr) or ""

            if not thumbnail:
                continue

            if "srcset" in attr:
                thumbnail = thumbnail.split(",")[0].strip().split(" ")[0]

            if thumbnail.startswith("data:"):
                continue

            return normalize_url(base_url, thumbnail)

    return ""


def extract_published_at(block, article_url="", fallback=""):
    published_at = extract_datetime_from_node(block)

    if published_at:
        return published_at

    if article_url:
        soup = make_soup(article_url)
        if soup is not None:
            published_at = extract_datetime_from_node(soup)

    return published_at or fallback


def extract_datetime_from_node(node):
    for selector in DATETIME_META_SELECTORS:
        tag = node.select_one(selector)
        if not tag:
            continue

        published_at = normalize_datetime_text(tag.get("content") or tag.get("value") or "")
        if published_at:
            return published_at

    for selector in DATETIME_TEXT_SELECTORS:
        tag = node.select_one(selector)
        if not tag:
            continue

        published_at = normalize_datetime_text(
            tag.get("datetime")
            or tag.get("content")
            or tag.get_text(" ", strip=True)
        )
        if published_at:
            return published_at

    return ""


def normalize_datetime_text(value):
    text = clean_text(value)

    if not text:
        return ""

    text = re.sub(r"\([^)]*GMT[^)]*\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(GMT|UTC)\s*[+-]?\s*\d*:?\d*\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(cập nhật|đăng lúc|ngày đăng|published|posted)\s*:?\s*", "", text, flags=re.IGNORECASE)
    text = clean_text(text.strip(" -|,"))

    parsed = _parse_iso_datetime(text) or _parse_rfc_datetime(text) or _parse_vietnamese_datetime(text)
    return parsed.strftime("%Y-%m-%d %H:%M:%S") if parsed else ""


def _parse_iso_datetime(text):
    candidate = text.strip()

    if not re.match(r"^\d{4}-\d{2}-\d{2}", candidate):
        return None

    candidate = candidate.replace("Z", "+00:00")

    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _parse_rfc_datetime(text):
    try:
        return parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _parse_vietnamese_datetime(text):
    match = re.search(
        r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})"
        r"(?:[,\s]+(?:lúc\s*)?(\d{1,2})[:h](\d{2})(?::(\d{2}))?)?",
        text,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    day, month, year, hour, minute, second = match.groups()

    try:
        return datetime(
            int(year),
            int(month),
            int(day),
            int(hour or 0),
            int(minute or 0),
            int(second or 0),
        )
    except ValueError:
        return None


def ensure_directory(path):
    Path(path).mkdir(parents=True, exist_ok=True)
