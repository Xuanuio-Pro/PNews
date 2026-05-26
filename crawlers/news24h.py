from datetime import datetime

from crawlers.base import clean_text, extract_image_url, make_soup, normalize_url
from services.classifier import classify_news_type, classify_topic


SOURCE = "24h"
BASE_URL = "https://www.24h.com.vn/"

NEWS24H_CATEGORIES = {
    "Tin tức": "https://www.24h.com.vn/tin-tuc-trong-ngay-c46.html",
    "Bóng đá": "https://www.24h.com.vn/bong-da-c48.html",
    "Kinh doanh": "https://www.24h.com.vn/kinh-doanh-c161.html",
    "Sức khỏe": "https://www.24h.com.vn/suc-khoe-doi-song-c62.html",
    "Giáo dục": "https://www.24h.com.vn/giao-duc-du-hoc-c216.html",
    "Pháp luật": "https://www.24h.com.vn/an-ninh-hinh-su-c51.html",
    "Công nghệ": "https://www.24h.com.vn/cong-nghe-thong-tin-c55.html",
    "Thời trang": "https://www.24h.com.vn/thoi-trang-c78.html",
    "Thế giới": "https://www.24h.com.vn/tin-tuc-quoc-te-c415.html",
}


def parse_article_block(block, category, crawled_at):
    title_tag = block.select_one("a[title], a")

    if not title_tag:
        return None

    title = clean_text(title_tag.get("title") or title_tag.get_text())
    url = normalize_url(BASE_URL, title_tag.get("href", ""))

    if not title or not url or len(title) < 20:
        return None

    summary_tag = block.select_one(".news-sapo, .cate-24h-foot-home-desc, .baiviet-sapo, p, span")
    summary = clean_text(summary_tag.get_text()) if summary_tag else ""
    thumbnail = extract_image_url(block, BASE_URL)
    content_topic = classify_topic(title, summary, default=category)

    return {
        "source": SOURCE,
        "title": title,
        "url": url,
        "crawled_at": crawled_at,
        "thumbnail": thumbnail,
        "summary": summary,
        "newspaper_type": classify_news_type(SOURCE),
        "content_topic": content_topic,
        "category": category,
    }


def crawl_category(category, url):
    soup = make_soup(url)

    if soup is None:
        return []

    articles = []
    crawled_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    blocks = soup.select("article, li, .news-item, .cate-24h-car-news-rand, .box-bai-viet")

    for block in blocks:
        article = parse_article_block(block, category, crawled_at)

        if article:
            articles.append(article)

    return articles


def crawl_24h():
    articles = []

    for category, url in NEWS24H_CATEGORIES.items():
        print(f"  - 24h/{category}")
        articles.extend(crawl_category(category, url))

    return articles
