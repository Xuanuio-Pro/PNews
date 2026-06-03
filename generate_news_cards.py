import argparse
import logging
import sys
from pathlib import Path

from config.logging_config import setup_logging
from config.settings import DATA_DIR, resolve_data_path
from services.image_generator import create_news_cards_from_csv
from services.storage import current_date_folder


setup_logging("crawler.log")
LOGGER = logging.getLogger("pnews.cards")


def safe_print(message):
    if logging.getLogger().handlers:
        LOGGER.info("%s", message)
        return
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        text = str(message).encode(encoding, errors="replace").decode(encoding)
        print(text)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate PNews cards from exported crawler CSV data."
    )
    parser.add_argument(
        "--input",
        default="data/exports/new_articles.csv",
        help="Path to exported articles CSV.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for generated news card images.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of cards to generate. Use 0 for all articles.",
    )
    parser.add_argument(
        "--brand",
        default="PNews",
        help="Brand text displayed at the top-right corner.",
    )
    parser.add_argument(
        "--require-thumbnail",
        action="store_true",
        help="Skip articles without HTTP thumbnail URLs.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete existing JPG/PNG files in output directory before generating.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    limit = None if args.limit == 0 else args.limit
    output_dir = args.output_dir or str(DATA_DIR / "generated_images" / current_date_folder())
    input_path = resolve_data_path(args.input)

    if not input_path.exists():
        safe_print(f"Không tìm thấy file input: {input_path}")
        return

    if is_empty_csv(input_path):
        safe_print(f"Không có bài mới trong file: {input_path}")
        return

    if args.clean:
        clean_output_dir(output_dir)

    output_paths = create_news_cards_from_csv(
        csv_path=str(input_path),
        output_dir=output_dir,
        limit=limit,
        brand_name=args.brand,
        require_thumbnail=args.require_thumbnail,
    )

    safe_print(f"Đã tạo {len(output_paths)} ảnh news card.")


def clean_output_dir(output_dir):
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)

    for pattern in ("*.jpg", "*.jpeg", "*.png"):
        for image_path in path.glob(pattern):
            image_path.unlink()


def is_empty_csv(path):
    with path.open("r", encoding="utf-8-sig") as file:
        lines = [line for line in file if line.strip()]
    return len(lines) <= 1


if __name__ == "__main__":
    main()
