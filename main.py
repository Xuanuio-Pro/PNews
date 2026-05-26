from crawlers.dantri import crawl_dantri
from crawlers.news24h import crawl_24h
from crawlers.vnexpress import crawl_vnexpress
from services.storage import (
    current_date_folder,
    remove_duplicates,
    save_all_articles,
    save_by_field,
    save_daily_outputs,
    save_json,
    split_new_articles,
    update_master_articles,
)


def crawl_all_sources():
    crawlers = [
        ("VNExpress", crawl_vnexpress),
        ("Dân trí", crawl_dantri),
        ("24h", crawl_24h),
    ]

    all_articles = []

    for source_name, crawl_func in crawlers:
        print(f"Đang crawl {source_name}...")
        articles = crawl_func()
        print(f"{source_name}: {len(articles)} bài")
        all_articles.extend(articles)

    return remove_duplicates(all_articles)


def save_outputs(articles):
    date_folder = current_date_folder()
    new_articles, master_articles = split_new_articles(articles)

    print(f"Số bài đã có trong kho master: {len(master_articles)}")
    print(f"Số bài mới trong lần crawl này: {len(new_articles)}")

    save_json(articles, "data/raw/articles.json")
    save_all_articles(articles, "data/exports/articles.csv")
    save_json(new_articles, "data/raw/new_articles.json")
    save_all_articles(new_articles, "data/exports/new_articles.csv")
    save_daily_outputs(articles, new_articles, date_folder)
    update_master_articles(new_articles)

    save_by_field(articles, "source", "data/processed/by_source")
    save_by_field(articles, "newspaper_type", "data/processed/by_newspaper_type")
    save_by_field(articles, "content_topic", "data/processed/by_content_topic")
    save_by_field(articles, "category", "data/processed/by_category")

    return new_articles, date_folder


def main():
    print("Bắt đầu crawl dữ liệu theo chuyên mục...")

    articles = crawl_all_sources()
    print(f"Tổng số bài sau khi xóa trùng: {len(articles)}")

    if not articles:
        print("Không crawl được bài nào. Bỏ qua bước lưu để tránh ghi đè dữ liệu cũ bằng file rỗng.")
        raise SystemExit(1)

    for article in articles[:10]:
        print(article["source"])
        print(article["category"])
        print(article["title"])
        print(article["url"])
        print("-" * 50)

    new_articles, date_folder = save_outputs(articles)
    print(f"Đã lưu dữ liệu ngày: {date_folder}")
    print(f"Ảnh news card nên tạo từ data/exports/new_articles.csv: {len(new_articles)} bài mới")
    print("Hoàn thành crawl dữ liệu.")


if __name__ == "__main__":
    main()
