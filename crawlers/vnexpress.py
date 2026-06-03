import logging
from datetime import datetime
from urllib.parse import urlparse

from crawlers.base import clean_text, extract_image_url, extract_published_at, make_soup, normalize_url


LOGGER = logging.getLogger(__name__)

SOURCE = "VNExpress"
BASE_URL = "https://vnexpress.net/"

VNEXPRESS_CATEGORIES = {
    "Khoa học - Công nghệ": {
        "url": "https://vnexpress.net/khoa-hoc-cong-nghe",
        "content_topic": "Khoa học - Công nghệ",
    },
    "Giáo dục": {
        "url": "https://vnexpress.net/giao-duc",
        "content_topic": "Giáo dục",
    },
}


def parse_article_block(block, category, content_topic, crawled_at):
    title_tag = block.select_one(
        "h3.title-news a[href], "
        "h2.title-news a[href], "
        "h4.title-news a[href], "
        ".title-news a[href]"
    )

    if not title_tag:
        title_tag = _best_article_link(block.select("a[href]"))

    return parse_article_link(title_tag, block, category, content_topic, crawled_at)


def parse_article_link(title_tag, block, category, content_topic, crawled_at):
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
        "newspaper_type": "Báo điện tử",
        "content_topic": content_topic,
        "category": category,
    }


def extract_summary(block, title):
    selectors = [
        "p.description a",
        "p.description",
        ".description a",
        ".description",
        ".lead",
        "p",
    ]

    for selector in selectors:
        summary_tag = block.select_one(selector)
        if not summary_tag:
            continue

        summary = clean_text(summary_tag.get_text(" ", strip=True))
        if summary and summary != title:
            return summary

    return ""


def crawl_category(category, info):
    url = info["url"]
    content_topic = info["content_topic"]
    soup = make_soup(url)

    if soup is None:
        LOGGER.warning("VNExpress/%s: không tải được HTML.", category)
        return []

    crawled_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    articles = []
    seen_urls = set()

    block_selectors = [
        "article.item-news",
        ".item-news",
        ".list-news-subfolder article",
        ".box-category-item",
    ]

    for selector in block_selectors:
        for block in soup.select(selector):
            article = parse_article_block(block, category, content_topic, crawled_at)
            _append_unique(articles, seen_urls, article)

    if len(articles) < 5:
        for title_tag in soup.select(
            "h3.title-news a[href], h2.title-news a[href], h4.title-news a[href]"
        ):
            block = _nearest_article_block(title_tag)
            article = parse_article_link(title_tag, block, category, content_topic, crawled_at)
            _append_unique(articles, seen_urls, article)

    if not articles:
        LOGGER.warning("VNExpress/%s: lấy được 0 bài. Cần kiểm tra selector.", category)

    return articles


def crawl_vnexpress():
    articles = []

    for category, info in VNEXPRESS_CATEGORIES.items():
        LOGGER.info("VNExpress/%s", category)
        articles.extend(crawl_category(category, info))

    return articles


def _nearest_article_block(tag):
    for parent in tag.parents:
        classes = parent.get("class") or []
        class_text = " ".join(classes)
        if parent.name == "article" or "item-news" in class_text:
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
    if not title or not url or len(title) < 10:
        return False

    parsed = urlparse(url)
    if "vnexpress.net" not in parsed.netloc:
        return False

    return parsed.path.endswith(".html")


def _append_unique(articles, seen_urls, article):
    if not article:
        return

    url = article.get("url")
    if not url or url in seen_urls:
        return

    articles.append(article)
    seen_urls.add(url)
