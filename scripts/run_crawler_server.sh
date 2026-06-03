#!/bin/bash
set -e

# Xác định thư mục dự án tương đối từ vị trí của file script
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# Tạo thư mục log nếu chưa có
mkdir -p logs

LOCKFILE="/tmp/pnews_crawler.lock"
CRON_LOG="logs/cron_crawler.log"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Khởi động tiến trình Cron Crawler ===" >> "$CRON_LOG"

# Sử dụng flock để ngăn chặn crawler chạy trùng lặp
exec 200>"$LOCKFILE"
if ! flock -n 200; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [WARN] Phát hiện tiến trình Crawler khác đang chạy. Thoát tiến trình này." >> "$CRON_LOG"
    exit 0
fi

# Tự động dọn dẹp lock file khi kết thúc
trap 'rm -f "$LOCKFILE"' EXIT

# Chạy crawler pipeline
echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] Khởi chạy pnews-crawler (main.py)..." >> "$CRON_LOG"
if docker compose run --rm pnews-crawler python -X utf8 main.py >> "$CRON_LOG" 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] Chạy crawler main.py hoàn tất." >> "$CRON_LOG"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] Lỗi khi chạy crawler main.py. Xem logs/crawler.log để biết chi tiết." >> "$CRON_LOG"
    exit 1
fi

# Đồng bộ dữ liệu vào SQLite CMS
echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] Khởi chạy đồng bộ sync_cms_from_csv.py..." >> "$CRON_LOG"
if docker compose run --rm pnews-crawler python scripts/sync_cms_from_csv.py >> "$CRON_LOG" 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] Đồng bộ hóa CMS thành công." >> "$CRON_LOG"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] Lỗi khi chạy đồng bộ sync_cms_from_csv.py." >> "$CRON_LOG"
    exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Kết thúc tiến trình Cron Crawler thành công ===" >> "$CRON_LOG"
exit 0
