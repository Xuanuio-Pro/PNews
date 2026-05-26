from datetime import datetime

from crawlers.base import clean_text, extract_image_url, make_soup, normalize_url
from services.classifier import classify_news_type, classify_topic


SOURCE = "Dân trí"
BASE_URL = "https://dantri.com.vn/"

DANTRI_CATEGORIES = {
    "Xã hội": "https://dantri.com.vn/xa-hoi.htm",
    "Kinh doanh": "https://dantri.com.vn/kinh-doanh.htm",
    "Bất động sản": "https://dantri.com.vn/bat-dong-san.htm",
    "Thể thao": "https://dantri.com.vn/the-thao.htm",
    "Sức khỏe": "https://dantri.com.vn/suc-khoe.htm",
    "Giáo dục": "https://dantri.com.vn/giao-duc.htm",
    "Pháp luật": "https://dantri.com.vn/phap-luat.htm",
    "Công nghệ": "https://dantri.com.vn/suc-manh-so.htm",
    "Giải trí": "https://dantri.com.vn/giai-tri.htm",
    "Thế giới": "https://dantri.com.vn/the-gioi.htm",
}


def parse_article_block(block, category, crawled_at):
    title_tag = block.select_one(
        "h3.article-title a, h2.article-title a, h3 a, h2 a, .article-title a"
    )

    if not title_tag:
        return None

    title = clean_text(title_tag.get_text())
    url = normalize_url(BASE_URL, title_tag.get("href", ""))

    if not title or not url or len(title) < 15:
        return None

    summary_tag = block.select_one(".article-excerpt, .article-sapo, .news-item__sapo, p")
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
    blocks = soup.select("article, .article-item, .news-item, .article.list")

    for block in blocks:
        article = parse_article_block(block, category, crawled_at)

        if article:
            articles.append(article)

    return articles


def crawl_dantri():
    articles = []

    for category, url in DANTRI_CATEGORIES.items():
        print(f"  - Dân trí/{category}")
        articles.extend(crawl_category(category, url))

    return articles
