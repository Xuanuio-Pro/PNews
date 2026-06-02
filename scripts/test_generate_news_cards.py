import csv
import json
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from services.image_generator import generate_news_card_with_status  # noqa: E402


CSV_PATH = BASE_DIR / "data" / "exports" / "articles.csv"
JSON_PATH = BASE_DIR / "data" / "raw" / "articles.json"
OUTPUT_DIR = "data/generated_images"
MIN_CARDS = 3
MAX_CARDS = 5


def safe_print(message):
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        text = str(message).encode(encoding, errors="replace").decode(encoding)
        print(text)


def load_articles():
    if CSV_PATH.exists():
        with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))
            if rows:
                safe_print(f"[DATA] Doc CSV: {CSV_PATH} ({len(rows)} bai)")
                return rows

    if JSON_PATH.exists():
        with JSON_PATH.open("r", encoding="utf-8") as file:
            data = json.load(file)
            if isinstance(data, list) and data:
                safe_print(f"[DATA] Doc JSON: {JSON_PATH} ({len(data)} bai)")
                return data

    safe_print("[DATA] Khong tim thay CSV/JSON hop le. Dung du lieu demo.")
    return [
        {
            "source": "IEC News",
            "title": "Sinh vien PTIT dat giai cao trong cuoc thi AI toan quoc",
            "url": "https://example.com/iec-demo-1",
            "crawled_at": "2026-05-27 09:00:00",
            "published_at": "2026-05-27 08:30:00",
            "thumbnail": "",
            "summary": "Nội dung đang được cập nhật.",
            "summary_source": "demo",
            "newspaper_type": "Trang tin truong dai hoc",
            "content_topic": "Giao duc",
            "category": "Giao duc",
        }
    ]


def ensure_minimum_articles(articles, min_count=MIN_CARDS):
    articles = list(articles or [])
    if len(articles) >= min_count:
        return articles

    seed = articles[0] if articles else {}
    while len(articles) < min_count:
        idx = len(articles) + 1
        clone = dict(seed)
        clone["title"] = f"{seed.get('title', 'Tin tuc IEC')} (demo {idx})"
        clone["url"] = f"{seed.get('url', 'https://example.com/iec-demo')}-{idx}"
        clone["thumbnail"] = ""
        if not clone.get("summary"):
            clone["summary"] = "Nội dung đang được cập nhật."
        articles.append(clone)
    return articles


def main():
    articles = ensure_minimum_articles(load_articles())
    total = min(MAX_CARDS, len(articles))
    selected = articles[:total]

    safe_print(f"[TEST] Tao thu {len(selected)} anh news card vao: {OUTPUT_DIR}")

    for index, article in enumerate(selected, start=1):
        output_path, used_fallback, thumbnail_source = generate_news_card_with_status(
            article,
            output_dir=OUTPUT_DIR,
        )
        mode = "FALLBACK" if used_fallback else "THUMBNAIL_THAT"
        title = str(article.get("title", "")).strip() or "Tin tuc IEC"
        safe_print(f"[{index}] {mode}: {title}")
        safe_print(f"     -> source: {thumbnail_source}")
        safe_print(f"     -> output: {output_path}")


if __name__ == "__main__":
    main()
