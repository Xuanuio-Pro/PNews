#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

export TZ="${TZ:-Asia/Ho_Chi_Minh}"

STATUS_FILTER="${1:-approved}"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/rerun_all_cards.log"
BACKUP_DIR="$PROJECT_DIR/data/generated_images.backup.$(date '+%Y%m%d-%H%M%S')"

mkdir -p "$LOG_DIR" "$PROJECT_DIR/data"

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

log "=== Starting rerun_all_cards status=${STATUS_FILTER} ==="

run_step "git fetch" git fetch --all --prune
run_step "git pull" git pull --ff-only
run_step "docker compose build" docker compose build pnews-web pnews-crawler pnews-scheduler
run_step "docker compose up" docker compose up -d pnews-web pnews-scheduler

if [ -d "$PROJECT_DIR/data/generated_images" ]; then
    run_step "backup generated_images" cp -a "$PROJECT_DIR/data/generated_images" "$BACKUP_DIR"
    log "[INFO] Backup created at ${BACKUP_DIR#$PROJECT_DIR/}"
fi

run_step "regenerate all cards" \
    docker compose --profile manual run --rm pnews-crawler \
    python -X utf8 scripts/regenerate_all_cards.py --status "$STATUS_FILTER"

run_step "restart web" docker compose restart pnews-web
run_step "healthcheck" curl -fsS http://localhost:8000/health

log "=== rerun_all_cards completed successfully status=${STATUS_FILTER} ==="
log "[INFO] Web should now serve regenerated cards with the new logo."
