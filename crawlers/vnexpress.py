from datetime import datetime

from crawlers.base import clean_text, extract_image_url, make_soup, normalize_url
from services.classifier import classify_news_type, classify_topic


SOURCE = "VNExpress"
BASE_URL = "https://vnexpress.net/"

VNEXPRESS_CATEGORIES = {
    "Thời sự": "https://vnexpress.net/thoi-su",
    "Kinh doanh": "https://vnexpress.net/kinh-doanh",
    "Công nghệ": "https://vnexpress.net/cong-nghe/",
    "Giáo dục": "https://vnexpress.net/giao-duc",
    "Sức khỏe": "https://vnexpress.net/suc-khoe",
    "Thể thao": "https://vnexpress.net/the-thao",
    "Pháp luật": "https://vnexpress.net/phap-luat",
    "Giải trí": "https://vnexpress.net/giai-tri",
    "Thế giới": "https://vnexpress.net/the-gioi",
}


def parse_article_block(block, category, crawled_at):
    title_tag = block.select_one("h3.title-news a, h2.title-news a, h4.title-news a, a")

    if not title_tag:
        return None

    title = clean_text(title_tag.get_text())
    url = normalize_url(BASE_URL, title_tag.get("href", ""))

    if not title or not url or len(title) < 15:
        return None

    summary_tag = block.select_one("p.description a, p.description, .description a, .description")
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
    blocks = soup.select("article.item-news")

    for block in blocks:
        article = parse_article_block(block, category, crawled_at)

        if article:
            articles.append(article)

    return articles


def crawl_vnexpress():
    articles = []

    for category, url in VNEXPRESS_CATEGORIES.items():
        print(f"  - VNExpress/{category}")
        articles.extend(crawl_category(category, url))

    return articles
