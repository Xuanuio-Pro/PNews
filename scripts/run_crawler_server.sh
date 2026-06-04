#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

mkdir -p logs

LOCKFILE="/tmp/pnews_crawler.lock"
CRON_LOG="logs/cron_crawler.log"
CARD_LIMIT="${CARD_LIMIT:-20}"
export TZ="${TZ:-Asia/Ho_Chi_Minh}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$CRON_LOG"
}

run_step() {
    step_name="$1"
    shift

    log "[INFO] Starting ${step_name}..."
    if "$@" >> "$CRON_LOG" 2>&1; then
        log "[INFO] ${step_name} finished."
    else
        log "[ERROR] ${step_name} failed."
        exit 1
    fi
}

log "=== Starting Cron Crawler ==="

exec 200>"$LOCKFILE"
if ! flock -n 200; then
    log "[WARN] Another crawler process is running. Exiting."
    exit 0
fi

trap 'rm -f "$LOCKFILE"' EXIT

run_step "main.py" \
    docker compose run --rm pnews-crawler python -X utf8 main.py

run_step "enrich_articles.py" \
    docker compose run --rm pnews-crawler python -X utf8 enrich_articles.py --input data/exports/new_articles.csv

run_step "generate_news_cards.py" \
    docker compose run --rm pnews-crawler python -X utf8 generate_news_cards.py --input data/exports/new_articles.csv --limit "$CARD_LIMIT" --clean

run_step "sync_cms_from_csv.py" \
    docker compose run --rm pnews-crawler python -X utf8 scripts/sync_cms_from_csv.py

log "=== Cron Crawler finished successfully ==="
