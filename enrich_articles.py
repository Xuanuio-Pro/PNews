import argparse

from services.article_enricher import enrich_missing_summaries
from services.storage import (
    current_date_folder,
    read_articles_csv,
    save_all_articles,
    save_json,
    update_articles_by_url,
)


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
        print(f"Không có bài viết để enrich: {args.input}")
        return

    enriched_articles = enrich_missing_summaries(
        articles,
        max_missing=args.max_missing,
        force_ai=args.force_ai,
    )
    save_all_articles(enriched_articles, output)

    if not args.no_sync:
        sync_enriched_articles(enriched_articles, args.date_folder)

    print(f"Đã enrich summary cho {len(enriched_articles)} bài.")


def sync_enriched_articles(enriched_articles, date_folder=None):
    date_folder = date_folder or current_date_folder()
    save_json(enriched_articles, "data/raw/new_articles.json")
    save_json(enriched_articles, f"data/daily/{date_folder}/raw/new_articles.json")
    save_all_articles(enriched_articles, f"data/daily/{date_folder}/exports/new_articles.csv")
    update_articles_by_url(enriched_articles, "data/master/master_articles.csv")


if __name__ == "__main__":
    main()
