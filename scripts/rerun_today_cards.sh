#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

export TZ="${TZ:-Asia/Ho_Chi_Minh}"

DATE_TO_RERUN="${1:-$(date '+%Y-%m-%d')}"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/rerun_today_cards.log"
OUTPUT_DIR="$PROJECT_DIR/data/generated_images/$DATE_TO_RERUN"
BACKUP_DIR="$PROJECT_DIR/data/generated_images/${DATE_TO_RERUN}.bak.$(date '+%Y%m%d-%H%M%S')"

mkdir -p "$LOG_DIR" "$PROJECT_DIR/data/generated_images"

log() {
    local message="$1"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $message" | tee -a "$LOG_FILE"
}

run_step() {
    local step_name="$1"
    shift

    log "[INFO] Starting ${step_name}..."
    if "$@" 2>&1 | tee -a "$LOG_FILE"; then
        log "[INFO] ${step_name} finished."
    else
        log "[ERROR] ${step_name} failed."
        exit 1
    fi
}

require_file() {
    local path="$1"
    local description="$2"
    if [ ! -f "$path" ]; then
        log "[ERROR] Missing ${description}: $path"
        exit 1
    fi
}

is_non_empty_csv() {
    local path="$1"
    [ -f "$path" ] && [ "$(grep -cve '^[[:space:]]*$' "$path")" -gt 1 ]
}

pick_input_csv() {
    local candidates=(
        "$PROJECT_DIR/data/daily/$DATE_TO_RERUN/exports/new_articles.csv"
        "$PROJECT_DIR/data/daily/$DATE_TO_RERUN/exports/articles.csv"
        "$PROJECT_DIR/data/exports/new_articles.csv"
        "$PROJECT_DIR/data/exports/articles.csv"
    )

    local path
    for path in "${candidates[@]}"; do
        if is_non_empty_csv "$path"; then
            printf '%s\n' "$path"
            return 0
        fi
    done

    return 1
}

log "=== Starting rerun_today_cards for ${DATE_TO_RERUN} ==="

require_file "$PROJECT_DIR/docker-compose.yml" "docker compose file"

run_step "git fetch" git fetch --all --prune
run_step "git pull" git pull --ff-only
run_step "docker compose build" docker compose build pnews-web pnews-crawler pnews-scheduler
run_step "docker compose up" docker compose up -d pnews-web pnews-scheduler

INPUT_CSV="$(pick_input_csv || true)"
if [ -z "${INPUT_CSV:-}" ]; then
    log "[ERROR] Could not find a non-empty CSV source for ${DATE_TO_RERUN}."
    log "[ERROR] Expected one of:"
    log "        data/daily/${DATE_TO_RERUN}/exports/new_articles.csv"
    log "        data/daily/${DATE_TO_RERUN}/exports/articles.csv"
    log "        data/exports/new_articles.csv"
    log "        data/exports/articles.csv"
    exit 1
fi

log "[INFO] Using input CSV: ${INPUT_CSV#$PROJECT_DIR/}"

if [ -d "$OUTPUT_DIR" ]; then
    run_step "backup existing generated images" cp -a "$OUTPUT_DIR" "$BACKUP_DIR"
    log "[INFO] Backup created at ${BACKUP_DIR#$PROJECT_DIR/}"
fi

run_step "enrich summaries" \
    docker compose --profile manual run --rm pnews-crawler \
    python -X utf8 enrich_articles.py \
    --input "${INPUT_CSV#$PROJECT_DIR/}" \
    --output "${INPUT_CSV#$PROJECT_DIR/}" \
    --date-folder "$DATE_TO_RERUN"

run_step "regenerate news cards" \
    docker compose --profile manual run --rm pnews-crawler \
    python -X utf8 generate_news_cards.py \
    --input "${INPUT_CSV#$PROJECT_DIR/}" \
    --output-dir "data/generated_images/$DATE_TO_RERUN" \
    --limit 0 \
    --clean

run_step "update DB image paths for rerun date" \
    docker compose --profile manual run --rm pnews-crawler \
    python -X utf8 scripts/regenerate_all_cards.py \
    --status all \
    --date "$DATE_TO_RERUN"

run_step "sync CMS from CSV" \
    docker compose --profile manual run --rm pnews-crawler \
    python -X utf8 scripts/sync_cms_from_csv.py

run_step "restart web" docker compose restart pnews-web

run_step "healthcheck" curl -fsS http://localhost:8000/health

log "=== rerun_today_cards completed successfully for ${DATE_TO_RERUN} ==="
log "[INFO] Web should now serve regenerated images from data/generated_images/${DATE_TO_RERUN}/"
