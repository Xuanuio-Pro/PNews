import json
import logging
import re
import unicodedata
from datetime import datetime

import pandas as pd
from pandas.errors import EmptyDataError

from config.settings import DATA_DIR, resolve_data_path


LOGGER = logging.getLogger(__name__)

OUTPUT_COLUMNS = [
    "source",
    "title",
    "url",
    "crawled_at",
    "published_at",
    "thumbnail",
    "summary",
    "summary_source",
    "newspaper_type",
    "content_topic",
    "category",
]


def slugify(value):
    value = (value or "khac").replace("Đ", "D").replace("đ", "d")
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_value = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value.lower()).strip("-")
    return ascii_value or "khac"


def current_date_folder():
    return datetime.now().strftime("%Y-%m-%d")


def remove_duplicates(articles):
    seen_urls = set()
    unique_articles = []

    for article in articles:
        url = article.get("url")

        if not url or url in seen_urls:
            continue

        unique_articles.append(article)
        seen_urls.add(url)

    return unique_articles


def to_dataframe(articles):
    return pd.DataFrame(articles, columns=OUTPUT_COLUMNS)


def sort_articles_by_published_at(articles):
    return sorted(
        articles,
        key=lambda article: (
            str(article.get("published_at") or ""),
            str(article.get("crawled_at") or ""),
            str(article.get("url") or ""),
        ),
        reverse=True,
    )


def read_articles_csv(path):
    path = resolve_data_path(path)

    if not path.exists():
        return []

    try:
        return pd.read_csv(path, encoding="utf-8-sig").fillna("").to_dict("records")
    except EmptyDataError:
        return []


def save_all_articles(articles, output_path="data/exports/articles.csv"):
    output_path = resolve_data_path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    to_dataframe(articles).to_csv(output_path, index=False, encoding="utf-8-sig")
    LOGGER.info("Đã lưu dữ liệu vào: %s", output_path)


def save_json(articles, output_path="data/raw/articles.json"):
    output_path = resolve_data_path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(articles, file, ensure_ascii=False, indent=2)

    LOGGER.info("Đã lưu JSON vào: %s", output_path)


def save_by_field(articles, field_name, base_folder):
    base_folder = resolve_data_path(base_folder)
    base_folder.mkdir(parents=True, exist_ok=True)

    for old_file in base_folder.glob("*.csv"):
        old_file.unlink()

    grouped_data = {}

    for article in articles:
        key = article.get(field_name) or "Khác"
        grouped_data.setdefault(key, []).append(article)

    for key, items in sorted(grouped_data.items()):
        output_path = base_folder / f"{slugify(key)}.csv"
        to_dataframe(items).to_csv(output_path, index=False, encoding="utf-8-sig")
        LOGGER.info("%s = %s: %s bài -> %s", field_name, key, len(items), output_path)


def split_new_articles(articles, master_path="data/master/master_articles.csv"):
    master_articles = read_articles_csv(master_path)
    existing_urls = {
        article.get("url")
        for article in master_articles
        if article.get("url")
    }

    new_articles = [
        article
        for article in articles
        if article.get("url") and article.get("url") not in existing_urls
    ]

    return remove_duplicates(new_articles), master_articles


def update_master_articles(new_articles, master_path="data/master/master_articles.csv", latest_articles=None):
    master_articles = read_articles_csv(master_path)
    latest_by_url = {
        article.get("url"): article
        for article in (latest_articles or [])
        if article.get("url")
    }
    merged_articles = []

    for article in master_articles:
        url = article.get("url")
        latest = latest_by_url.get(url)

        if latest:
            updated_article = dict(article)
            for column in OUTPUT_COLUMNS:
                latest_value = latest.get(column)
                if latest_value not in (None, ""):
                    updated_article[column] = latest_value
            merged_articles.append(updated_article)
        else:
            merged_articles.append(article)

    merged_articles = remove_duplicates(merged_articles + new_articles)
    save_all_articles(merged_articles, master_path)
    return merged_articles


def update_articles_by_url(updated_articles, target_path):
    target_articles = read_articles_csv(target_path)
    updated_by_url = {
        article.get("url"): article
        for article in updated_articles
        if article.get("url")
    }

    if not target_articles:
        save_all_articles(updated_articles, target_path)
        return updated_articles

    merged_articles = []

    for article in target_articles:
        url = article.get("url")
        merged_articles.append(updated_by_url.get(url, article))

    existing_urls = {article.get("url") for article in merged_articles}

    for article in updated_articles:
        if article.get("url") not in existing_urls:
            merged_articles.append(article)

    save_all_articles(merged_articles, target_path)
    return merged_articles


def save_daily_outputs(articles, new_articles, date_folder=None):
    date_folder = date_folder or current_date_folder()
    daily_base = DATA_DIR / "daily" / date_folder

    save_json(articles, daily_base / "raw" / "articles.json")
    save_all_articles(articles, daily_base / "exports" / "articles.csv")
    save_json(new_articles, daily_base / "raw" / "new_articles.json")
    save_all_articles(new_articles, daily_base / "exports" / "new_articles.csv")

    return daily_base
