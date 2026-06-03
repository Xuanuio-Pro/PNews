import argparse
import logging

from config.logging_config import setup_logging
from services.article_enricher import enrich_missing_summaries
from services.storage import (
    current_date_folder,
    read_articles_csv,
    save_all_articles,
    save_json,
    update_articles_by_url,
)


setup_logging("crawler.log")
LOGGER = logging.getLogger("pnews.enrich")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Enrich missing article summaries before generating news cards."
    )
    parser.add_argument(
        "--input",
        default="data/exports/new_articles.csv",
        help="Input CSV file.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output CSV file. Defaults to overwriting input.",
    )
    parser.add_argument(
        "--no-sync",
        action="store_true",
        help="Do not sync enriched new articles back to daily/raw/master files.",
    )
    parser.add_argument(
        "--max-missing",
        type=int,
        default=None,
        help="Maximum number of missing summaries to enrich in this run.",
    )
    parser.add_argument(
        "--date-folder",
        default=None,
        help="Daily snapshot folder to sync, for example 2026-05-19.",
    )
    parser.add_argument(
        "--force-ai",
        action="store_true",
        help="Reprocess summaries created by fallback/missing_content/pending when API quota is available.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    output = args.output or args.input
    articles = read_articles_csv(args.input)

    if not articles:
        LOGGER.info("Không có bài viết để enrich: %s", args.input)
        return

    enriched_articles = enrich_missing_summaries(
        articles,
        max_missing=args.max_missing,
        force_ai=args.force_ai,
    )
    save_all_articles(enriched_articles, output)

    if not args.no_sync:
        sync_enriched_articles(enriched_articles, args.date_folder)

    LOGGER.info("Đã enrich summary cho %s bài.", len(enriched_articles))


def sync_enriched_articles(enriched_articles, date_folder=None):
    date_folder = date_folder or current_date_folder()
    save_json(enriched_articles, "data/raw/new_articles.json")
    save_json(enriched_articles, f"data/daily/{date_folder}/raw/new_articles.json")
    save_all_articles(enriched_articles, f"data/daily/{date_folder}/exports/new_articles.csv")
    update_articles_by_url(enriched_articles, "data/master/master_articles.csv")


if __name__ == "__main__":
    main()
