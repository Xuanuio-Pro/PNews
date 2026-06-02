import re
from datetime import datetime
from urllib.parse import urlparse

from crawlers.base import clean_text, extract_image_url, extract_published_at, make_soup, normalize_url


SOURCE = "Báo Chính phủ"
BASE_URL = "https://baochinhphu.vn/"
CATEGORY = "Khoa giáo - Khoa học công nghệ"
CONTENT_TOPIC = "Khoa học - Giáo dục"
LIST_URL = "https://baochinhphu.vn/khoa-giao/khoa-hoc-cong-nghe.htm"


def parse_article_block(block, crawled_at):
    title_tag = block.select_one(
        "h1 a[href], h2 a[href], h3 a[href], h4 a[href], "
        ".title a[href], .news-title a[href], .story-title a[href]"
    )

    if not title_tag:
        title_tag = _best_article_link(block.select("a[href]"))

    return parse_article_link(title_tag, block, crawled_at)


def parse_article_link(title_tag, block, crawled_at):
    if not title_tag:
        return None

    title = clean_text(title_tag.get("title") or title_tag.get_text(" ", strip=True))
    url = normalize_url(BASE_URL, title_tag.get("href", ""))

    if not _is_valid_article(title, url):
        return None

    summary = extract_summary(block, title)
    thumbnail = extract_image_url(block, BASE_URL)
    published_at = extract_published_at(block, url, fallback=crawled_at)

    return {
        "source": SOURCE,
        "title": title,
        "url": url,
        "crawled_at": crawled_at,
        "published_at": published_at,
        "thumbnail": thumbnail,
        "summary": summary,
        "summary_source": "crawler" if summary else "pending",
        "newspaper_type": "Cổng thông tin Chính phủ",
        "content_topic": CONTENT_TOPIC,
        "category": CATEGORY,
    }


def extract_summary(block, title):
    selectors = [
        ".summary",
        ".sapo",
        ".desc",
        ".description",
        ".news-desc",
        ".story-desc",
        "p",
    ]

    for selector in selectors:
        summary_tag = block.select_one(selector)
        if not summary_tag:
            continue

        summary = clean_text(summary_tag.get_text(" ", strip=True))
        if summary and summary != title and len(summary) >= 20:
            return summary

    return ""


def crawl_baochinhphu():
    print(f"  - Báo Chính phủ/{CATEGORY}")
    soup = make_soup(LIST_URL)

    if soup is None:
        print("[WARN] Báo Chính phủ: không tải được HTML.")
        return []

    crawled_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    articles = []
    seen_urls = set()

    block_selectors = [
        ".list__main .box-category-item",
        ".list__main .box-category-item-sub",
        ".list__lmain .box-stream-item",
    ]

    for selector in block_selectors:
        for block in soup.select(selector):
            article = parse_article_block(block, crawled_at)
            _append_unique(articles, seen_urls, article)

    if len(articles) < 5:
        for title_tag in soup.select(
            ".list__main h2 a[href], "
            ".list__main h3 a[href], "
            ".list__lmain h2 a[href], "
            ".list__lmain h3 a[href]"
        ):
            block = _nearest_article_block(title_tag)
            article = parse_article_link(title_tag, block, crawled_at)
            _append_unique(articles, seen_urls, article)

    if not articles:
        print("[WARN] Báo Chính phủ: lấy được 0 bài. Cần kiểm tra selector.")

    return articles


def _nearest_article_block(tag):
    for parent in tag.parents:
        classes = " ".join(parent.get("class") or [])
        if parent.name in {"article", "li"}:
            return parent
        if any(marker in classes for marker in ("item", "news", "story", "list")):
            return parent
    return tag.parent or tag


def _best_article_link(links):
    for link in links:
        title = clean_text(link.get("title") or link.get_text(" ", strip=True))
        url = normalize_url(BASE_URL, link.get("href", ""))
        if _is_valid_article(title, url):
            return link
    return None


def _is_valid_article(title, url):
    if not title or not url or len(title) < 15:
        return False

    if url.rstrip("/") == LIST_URL.rstrip("/"):
        return False

    parsed = urlparse(url)
    if "baochinhphu.vn" not in parsed.netloc:
        return False

    return bool(re.search(r"-\d{8,}\.htm$", parsed.path))


def _append_unique(articles, seen_urls, article):
    if not article:
        return

    url = article.get("url")
    if not url or url in seen_urls:
        return

    articles.append(article)
    seen_urls.add(url)
