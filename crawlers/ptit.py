import logging
from datetime import datetime
from urllib.parse import urlparse

from crawlers.base import (
    clean_text,
    extract_datetime_from_node,
    extract_image_url,
    make_soup,
    normalize_url,
)


LOGGER = logging.getLogger(__name__)

SOURCE = "PTIT"
BASE_URL = "https://ptit.edu.vn/"
CATEGORY = "Tin tức chung"
CONTENT_TOPIC = "Tin tức PTIT"
LIST_URL = "https://ptit.edu.vn/tin-tuc-su-kien/tin-tuc/tin-tuc-chung/"


def parse_article_block(block, crawled_at):
    title_tag = block.select_one(
        ".entry-title a[href], "
        ".elementor-post__title a[href], "
        ".ovaev-content h2 a[href], "
        ".ovaev-content h3 a[href], "
        "h2 a[href], h3 a[href], h4 a[href], "
        "a[title][href]"
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
    published_at = extract_datetime_from_node(block)

    if not summary or not thumbnail or not published_at:
        detail_soup = make_soup(url)
        if detail_soup is not None:
            if not summary:
                summary = extract_detail_summary(detail_soup, title)
            if not thumbnail:
                thumbnail = extract_detail_image(detail_soup)
            if not published_at:
                published_at = extract_datetime_from_node(detail_soup)

    return {
        "source": SOURCE,
        "title": title,
        "url": url,
        "crawled_at": crawled_at,
        "published_at": published_at or crawled_at,
        "thumbnail": thumbnail,
        "summary": summary,
        "summary_source": "crawler" if summary else "pending",
        "newspaper_type": "Trang tin trường đại học",
        "content_topic": CONTENT_TOPIC,
        "category": CATEGORY,
    }


def extract_summary(block, title):
    selectors = [
        ".entry-summary",
        ".elementor-post__excerpt",
        ".post-excerpt",
        ".excerpt",
        ".ovaev-short-desc",
        ".ovaev-content p",
        "p",
    ]

    for selector in selectors:
        summary_tag = block.select_one(selector)
        if not summary_tag:
            continue

        summary = clean_text(summary_tag.get_text(" ", strip=True))
        if summary and summary != title and "xem chi tiết" not in summary.lower():
            return summary

    return ""


def extract_detail_summary(soup, title):
    for meta_summary in _meta_contents(soup, "meta[name='description'], meta[property='og:description']"):
        if _is_useful_summary(meta_summary, title):
            return _trim_summary(meta_summary)

    for scope in _detail_content_scopes(soup):
        for paragraph in scope.select("p"):
            summary = clean_text(paragraph.get_text(" ", strip=True))
            if _is_useful_summary(summary, title):
                return _trim_summary(summary)

    return ""


def extract_detail_image(soup):
    for meta_image in _meta_contents(
        soup,
        "meta[property='og:image'], meta[property='og:image:secure_url'], meta[name='twitter:image']",
    ):
        if meta_image:
            return normalize_url(BASE_URL, meta_image)

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
    for scope in _detail_content_scopes(soup):
        for img in scope.select("img"):
            for attr in image_attrs:
                value = img.get(attr) or ""
                if not value:
                    continue
                if "srcset" in attr:
                    value = value.split(",")[0].strip().split(" ")[0]
                if value.startswith("data:"):
                    continue
                return normalize_url(BASE_URL, value)

    return ""


def _detail_content_scopes(soup):
    selectors = [
        ".entry-content",
        ".post-content",
        ".elementor-widget-theme-post-content",
        ".elementor-widget-container",
        ".single-post-content",
        ".ovaev-content",
        "article",
    ]
    scopes = [scope for selector in selectors for scope in soup.select(selector)]
    return scopes or [soup]


def _meta_contents(soup, selector):
    return [
        clean_text(tag.get("content", ""))
        for tag in soup.select(selector)
        if tag.get("content")
    ]


def _is_useful_summary(summary, title):
    summary = clean_text(summary)
    if len(summary) < 60:
        return False
    normalized = summary.lower()
    if normalized == clean_text(title).lower():
        return False
    ignored_fragments = (
        "menu",
        "trang chủ",
        "chi tiết bài viết",
        "tin tức & sự kiện",
        "xem chi tiết",
    )
    return not any(fragment in normalized for fragment in ignored_fragments)


def _trim_summary(summary, max_length=320):
    summary = clean_text(summary)
    if len(summary) <= max_length:
        return summary
    trimmed = summary[:max_length].rsplit(" ", 1)[0].rstrip(" ,.;:")
    return f"{trimmed}..."


def crawl_ptit():
    LOGGER.info("PTIT/%s", CATEGORY)
    soup = make_soup(LIST_URL)

    if soup is None:
        LOGGER.warning("PTIT: không tải được HTML.")
        return []

    crawled_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    articles = []
    seen_urls = set()

    block_selectors = [
        "article",
        ".post",
        ".elementor-post",
        ".ovaev-content",
        ".entry",
        ".blog-item",
        ".post-item",
        ".type-post",
    ]

    for selector in block_selectors:
        for block in soup.select(selector):
            article = parse_article_block(block, crawled_at)
            _append_unique(articles, seen_urls, article)

    if len(articles) < 5:
        for title_tag in soup.select(
            ".entry-title a[href], .elementor-post__title a[href], "
            "h2 a[href], h3 a[href], h4 a[href]"
        ):
            block = _nearest_article_block(title_tag)
            article = parse_article_link(title_tag, block, crawled_at)
            _append_unique(articles, seen_urls, article)

    if not articles:
        LOGGER.warning("PTIT: lấy được 0 bài. Cần kiểm tra selector.")

    return articles


def _nearest_article_block(tag):
    for parent in tag.parents:
        classes = " ".join(parent.get("class") or [])
        if parent.name == "article":
            return parent
        if any(marker in classes for marker in ("post", "entry", "elementor-post", "ovaev")):
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

    if title.lower() in {"xem chi tiết", "xem chi tiet"}:
        return False

    if url.rstrip("/") == LIST_URL.rstrip("/"):
        return False

    parsed = urlparse(url)
    if "ptit.edu.vn" not in parsed.netloc:
        return False

    path = parsed.path.strip("/")
    if not path or path in {"tin-tuc-su-kien", "tin-tuc-su-kien/tin-tuc", "tin-tuc-su-kien/tin-tuc/tin-tuc-chung"}:
        return False

    return True


def _append_unique(articles, seen_urls, article):
    if not article:
        return

    url = article.get("url")
    if not url or url in seen_urls:
        return

    articles.append(article)
    seen_urls.add(url)
