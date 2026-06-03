#!/bin/bash
set -e

# Xác định thư mục dự án tương đối từ vị trí của file script
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

mkdir -p backups
mkdir -p logs

BACKUP_LOG="logs/backup.log"
TIMESTAMP=$(date '+%Y-%m-%d_%H-%M')
BACKUP_FILE="backups/pnews_backup_${TIMESTAMP}.tar.gz"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Bắt đầu tiến trình sao lưu dữ liệu ===" >> "$BACKUP_LOG"

# Kiểm tra sự tồn tại của database và các thư mục quan trọng trước khi backup
ITEMS_TO_BACKUP=""
for item in data/cms.sqlite3 data/generated_images data/uploads data/master data/exports logs; do
    if [ -e "$item" ]; then
        ITEMS_TO_BACKUP="$ITEMS_TO_BACKUP $item"
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] Mục $item không tồn tại, bỏ qua." >> "$BACKUP_LOG"
    fi
done

if [ -z "$ITEMS_TO_BACKUP" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] Không tìm thấy dữ liệu nào để sao lưu." >> "$BACKUP_LOG"
    exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] Đang nén các thư mục dữ liệu: $ITEMS_TO_BACKUP..." >> "$BACKUP_LOG"

# Nén dữ liệu thành file tar.gz
if tar -czf "$BACKUP_FILE" $ITEMS_TO_BACKUP >> "$BACKUP_LOG" 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] Đã tạo file sao lưu thành công: $BACKUP_FILE" >> "$BACKUP_LOG"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] Gặp lỗi trong quá trình tạo file nén sao lưu." >> "$BACKUP_LOG"
    exit 1
fi

# Dọn dẹp chỉ giữ lại tối đa 14 bản backup gần nhất
echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] Kiểm tra và dọn dẹp các bản sao lưu cũ..." >> "$BACKUP_LOG"
# Liệt kê các file backup xếp theo thời gian mới nhất (ls -t), lấy từ dòng thứ 15 trở đi để xóa
BACKUP_COUNT=$(ls -1t backups/pnews_backup_*.tar.gz 2>/dev/null | wc -l)
if [ "$BACKUP_COUNT" -gt 14 ]; then
    # tail -n +15 lấy từ dòng 15 trở đi
    ls -1t backups/pnews_backup_*.tar.gz | tail -n +15 | while read -r file; do
        rm -f "$file"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] Đã xóa bản sao lưu cũ vượt định mức: $file" >> "$BACKUP_LOG"
    done
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === Kết thúc tiến trình sao lưu dữ liệu thành công ===" >> "$BACKUP_LOG"
exit 0
