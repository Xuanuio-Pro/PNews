#!/bin/bash
set -e

# Xác định thư mục dự án tương đối từ vị trí của file script
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo "=== BẮT ĐẦU KIỂM TRA RUNTIME HỆ THỐNG ==="

echo "[1/8] Kiểm tra cấu hình Docker Compose..."
docker compose config

echo "[2/8] Build các Docker containers..."
docker compose build

echo "[3/8] Khởi chạy dịch vụ pnews-web..."
docker compose up -d pnews-web

echo "[4/8] Đợi dịch vụ khởi động và kiểm tra Health Endpoint..."
# Đợi tối đa 30s cho web server khởi động và trả về HTTP 200 từ healthcheck
SUCCESS=0
for i in {1..30}; do
    if docker compose exec -T pnews-web python -c "import urllib.request, json; res=urllib.request.urlopen('http://localhost:8000/health'); data=json.loads(res.read().decode()); exit(0 if data['status']=='ok' else 1)" >/dev/null 2>&1; then
        echo "   -> [OK] Health endpoint phản hồi chính xác (status: ok)."
        SUCCESS=1
        break
    fi
    sleep 1
done

if [ $SUCCESS -ne 1 ]; then
    echo "   -> [FAIL] Không truy cập được Health endpoint hoặc ứng dụng bị degraded."
    docker compose logs pnews-web
    exit 1
fi

echo "[5/8] Kiểm tra trang client và admin..."
docker compose exec -T pnews-web python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/client', timeout=10).read()" >/dev/null
docker compose exec -T pnews-web python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/admin', timeout=10).read()" >/dev/null
echo "   -> [OK] /client và /admin phản hồi."

echo "[6/8] Chạy thử dịch vụ pnews-crawler..."
docker compose --profile manual run --rm pnews-crawler python -X utf8 main.py

echo "[7/8] Xác minh cơ sở dữ liệu SQLite..."
if [ -f "data/cms.sqlite3" ]; then
    echo "   -> [OK] Database data/cms.sqlite3 tồn tại."
else
    echo "   -> [FAIL] Không tìm thấy cơ sở dữ liệu data/cms.sqlite3."
    exit 1
fi

echo "[8/8] Xác minh thư mục logs..."
if [ -d "logs" ] && [ -f "logs/crawler.log" ] && [ -f "logs/app.log" ]; then
    echo "   -> [OK] Thư mục logs và file logs hoạt động bình thường."
else
    echo "   -> [WARN] Thư mục logs hoặc file log chưa được tạo đầy đủ."
fi

echo "=== KIỂM TRA RUNTIME THÀNH CÔNG ==="
exit 0
