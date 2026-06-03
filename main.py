import logging
from collections import Counter
import sys

from config.logging_config import setup_logging
from crawlers.baochinhphu import crawl_baochinhphu
from crawlers.ptit import crawl_ptit
from crawlers.vnexpress import crawl_vnexpress
from services.storage import (
    current_date_folder,
    remove_duplicates,
    save_all_articles,
    save_by_field,
    save_daily_outputs,
    save_json,
    sort_articles_by_published_at,
    split_new_articles,
    update_master_articles,
)

# Cấu hình logging tập trung ghi vào logs/crawler.log và logs/error.log
setup_logging("crawler.log")
LOGGER = logging.getLogger("pnews.crawler")


def crawl_all_sources():
    crawlers = [
        ("VNExpress", crawl_vnexpress),
        ("Báo Chính phủ", crawl_baochinhphu),
        ("PTIT", crawl_ptit),
    ]

    all_articles = []

    for source_name, crawl_func in crawlers:
        LOGGER.info(f"Đang crawl {source_name}...")
        try:
            articles = crawl_func()
            LOGGER.info(f"{source_name}: thu thập được {len(articles)} bài")
            if not articles:
                LOGGER.warning(f"{source_name}: lấy được 0 bài. Pipeline vẫn tiếp tục với các nguồn khác.")
            all_articles.extend(articles)
        except Exception as e:
            LOGGER.error(f"Lỗi khi crawl nguồn {source_name}: {str(e)}", exc_info=True)

    return remove_duplicates(all_articles)


def save_outputs(articles):
    articles = sort_articles_by_published_at(articles)
    date_folder = current_date_folder()
    new_articles, master_articles = split_new_articles(articles)

    LOGGER.info(f"Số bài đã có trong kho master: {len(master_articles)}")
    LOGGER.info(f"Số bài mới trong lần crawl này: {len(new_articles)}")

    save_json(articles, "data/raw/articles.json")
    save_all_articles(articles, "data/exports/articles.csv")
    save_json(new_articles, "data/raw/new_articles.json")
    save_all_articles(new_articles, "data/exports/new_articles.csv")
    save_daily_outputs(articles, new_articles, date_folder)
    update_master_articles(new_articles, latest_articles=articles)

    save_by_field(articles, "source", "data/processed/by_source")
    save_by_field(articles, "newspaper_type", "data/processed/by_newspaper_type")
    save_by_field(articles, "content_topic", "data/processed/by_content_topic")
    save_by_field(articles, "category", "data/processed/by_category")

    return new_articles, date_folder


def log_sample_articles(articles):
    for article in articles[:10]:
        LOGGER.info(
            f"Sample article - Nguồn: {article.get('source')} | Chuyên mục: {article.get('category')} | Tiêu đề: {article.get('title')} | URL: {article.get('url')}"
        )


def log_source_stats(articles):
    source_counts = Counter(article.get("source", "Không xác định") for article in articles)
    LOGGER.info("Thống kê nguồn sau khi xóa trùng:")
    for source, count in sorted(source_counts.items()):
        LOGGER.info(f"  - {source}: {count} bài")


def main():
    LOGGER.info("Bắt đầu pipeline crawl dữ liệu v2.0 cho IEC/PTIT...")

    try:
        articles = crawl_all_sources()
        LOGGER.info(f"Tổng số bài sau khi xóa trùng: {len(articles)}")

        if not articles:
            LOGGER.error("Không crawl được bài nào. Bỏ qua bước lưu để tránh ghi đè dữ liệu cũ bằng file rỗng.")
            sys.exit(1)

        log_source_stats(articles)
        log_sample_articles(articles)

        new_articles, date_folder = save_outputs(articles)
        LOGGER.info(f"Đã lưu dữ liệu ngày: {date_folder}")
        LOGGER.info(f"Ảnh news card nên tạo từ data/exports/new_articles.csv: {len(new_articles)} bài mới")
        LOGGER.info("Hoàn thành pipeline crawl dữ liệu v2.0.")
    except Exception as e:
        LOGGER.critical(f"Lỗi nghiêm trọng trong quá trình chạy crawler: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
