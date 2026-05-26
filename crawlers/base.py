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
    img = block.select_one("img")

    if not img:
        return ""

    thumbnail = (
        img.get("data-src")
        or img.get("data-original")
        or img.get("data-lazy-src")
        or img.get("data-thumb")
        or img.get("src")
        or ""
    )

    if not thumbnail and img.get("srcset"):
        thumbnail = img.get("srcset").split(",")[0].strip().split(" ")[0]

    return normalize_url(base_url, thumbnail)


def ensure_directory(path):
    Path(path).mkdir(parents=True, exist_ok=True)
