#!/bin/bash
set -e

# Xác định thư mục dự án tương đối từ vị trí của file script
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

BACKUP_FILE="$1"
RESTORE_LOG="logs/restore.log"
mkdir -p logs

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Bắt đầu tiến trình khôi phục dữ liệu ===" >> "$RESTORE_LOG"

if [ -z "$BACKUP_FILE" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] Thiếu tham số đường dẫn file backup. Cú pháp: ./restore_data.sh <duong_dan_file_backup>" | tee -a "$RESTORE_LOG"
    exit 1
fi

if [ ! -f "$BACKUP_FILE" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] Không tìm thấy file backup tại: $BACKUP_FILE" | tee -a "$RESTORE_LOG"
    exit 1
fi

# 1. Dừng pnews-web trước khi khôi phục
echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] Đang tạm dừng dịch vụ pnews-web..." >> "$RESTORE_LOG"
docker compose stop pnews-web >> "$RESTORE_LOG" 2>&1 || true

# 2. Backup nhanh data hiện tại trước khi ghi đè đề phòng sự cố
echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] Thực hiện sao lưu nhanh dữ liệu hiện tại trước khi ghi đè..." >> "$RESTORE_LOG"
PRE_RESTORE_BACKUP="backups/pre_restore_backup_$(date '+%Y-%m-%d_%H-%M-%S').tar.gz"
if [ -d "data" ] || [ -d "logs" ]; then
    tar -czf "$PRE_RESTORE_BACKUP" data logs >> "$RESTORE_LOG" 2>&1 || true
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] Đã lưu dự phòng dữ liệu hiện tại vào: $PRE_RESTORE_BACKUP" >> "$RESTORE_LOG"
fi

# 3. Giải nén đè lên dự án
echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] Đang giải nén khôi phục dữ liệu từ $BACKUP_FILE..." >> "$RESTORE_LOG"
if tar -xzf "$BACKUP_FILE" >> "$RESTORE_LOG" 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] Giải nén dữ liệu hoàn thành." >> "$RESTORE_LOG"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] Lỗi khi giải nén file backup. Cố gắng khởi động lại dịch vụ..." >> "$RESTORE_LOG"
    docker compose start pnews-web >> "$RESTORE_LOG" 2>&1 || true
    exit 1
fi

# 4. Khởi động lại dịch vụ
echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] Khởi động lại dịch vụ pnews-web..." >> "$RESTORE_LOG"
docker compose start pnews-web >> "$RESTORE_LOG" 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Kết thúc tiến trình khôi phục dữ liệu thành công ===" >> "$RESTORE_LOG"
echo "Khôi phục thành công. Vui lòng xem logs/restore.log để biết chi tiết."
exit 0
