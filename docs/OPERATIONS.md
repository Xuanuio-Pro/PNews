# Hướng dẫn Vận hành và Quản trị Hệ thống PNews (Operations Guide)

Tài liệu này cung cấp các lệnh quản trị, giám sát, kiểm tra sức khỏe hệ thống và các bước xử lý sự cố thường gặp cho quản trị viên hệ thống PNews.

---

## 1. Giám sát Trạng thái Dịch vụ

### Kiểm tra các container đang hoạt động
```bash
docker compose ps
```
Trạng thái đúng:
- `pnews_web` ở trạng thái `Up` (healthy).
- `pnews_crawler` ở trạng thái `Exit 0` hoặc trống (chỉ chạy khi được gọi).

### Kiểm tra lượng tài nguyên tiêu thụ (CPU/RAM)
```bash
docker stats
```

---

## 2. Quản trị Dịch vụ Web CMS

### Khởi động lại dịch vụ Web
```bash
docker compose restart pnews-web
```

### Xem log trực tiếp của Web Server
```bash
docker compose logs -f pnews-web
```
Hoặc xem trực tiếp file log quay vòng tại máy host:
```bash
tail -n 100 -f logs/app.log
```

---

## 3. Quản trị Crawler Dữ liệu

### Chạy Crawler thủ công bằng Docker Compose
Khi cần thu thập dữ liệu lập tức ngoài khung giờ 7h sáng:
```bash
# Thực thi pipeline thu thập tin tức
docker compose --profile manual run --rm pnews-crawler python -X utf8 main.py

# Đồng bộ hóa dữ liệu vừa thu thập vào SQLite DB của Web app
docker compose --profile manual run --rm pnews-crawler python scripts/sync_cms_from_csv.py
```
Hoặc chạy thông qua shell script vận hành (có cơ chế chống chạy trùng lặp):
```bash
./scripts/run_crawler_server.sh
```

### Kiểm tra log chạy của Crawler
- **Nhật ký tiến trình chi tiết**: `logs/crawler.log`
- **Nhật ký kích hoạt tự động từ Cron**: `logs/cron_crawler.log`

---

## 4. Kiểm tra sức khỏe (Healthcheck) và Dung lượng đĩa

### Xem kết quả Healthcheck của container
```bash
docker inspect --format='{{json .State.Health}}' pnews_web
```

### Gọi trực tiếp Endpoint Healthcheck từ máy chủ
```bash
curl -i http://localhost:8000/health
```
Phản hồi mẫu thành công (HTTP 200 OK):
```json
{
  "status": "ok",
  "database": "ok",
  "time": "2026-06-03 21:55:00",
  "app": "PNews"
}
```

### Kiểm tra dung lượng lưu trữ trên máy chủ
Dữ liệu crawler, news cards và logs có thể chiếm dung lượng theo thời gian. Kiểm tra bằng:
```bash
# Xem dung lượng thư mục dự án
du -sh /opt/pnews

# Xem không gian trống trên toàn hệ đĩa cứng
df -h
```

---

## 5. Những lỗi thường gặp và cách xử lý

### Sự cố 1: Web CMS phản hồi chậm hoặc lỗi cơ sở dữ liệu bị khóa (`database is locked`)
- **Nguyên nhân**: SQLite chịu ghi đồng thời bị giới hạn. Có thể do crawler đang đồng bộ lượng dữ liệu quá lớn hoặc tiến trình crawler trước đó bị treo chưa giải phóng khóa DB.
- **Cách xử lý**:
  1. Kiểm tra xem có tiến trình crawler nào bị treo không:
     ```bash
     ps aux | grep main.py
     ```
  2. Bật chế độ WAL (Write-Ahead Logging) cho SQLite (đã được cấu hình tự động trong code).
  3. Khởi động lại container web để làm sạch các kết nối treo:
     ```bash
     docker compose restart pnews-web
     ```

### Sự cố 2: Lỗi Font chữ hiển thị trên News Card bị vỡ hoặc ô vuông (tofu)
- **Nguyên nhân**: Font chữ DejaVu Sans chưa được cài đặt trong môi trường chạy Docker hoặc file font bị mất.
- **Cách xử lý**:
  Xác minh xem gói `fonts-dejavu-core` có được cài đặt thành công khi build Docker không. Bạn có thể chui vào container và kiểm tra sự tồn tại của font:
  ```bash
  docker compose exec pnews-web ls /usr/share/fonts/truetype/dejavu/
  ```
  Nếu không thấy tệp `DejaVuSans.ttf`, hãy thực hiện build lại container bằng cờ `--no-cache`:
  ```bash
  docker compose build --no-cache pnews-web
  docker compose up -d pnews-web
  ```

### Sự cố 3: Lỗi kết nối API AI (Gemini/Groq) hoặc lỗi Đăng tải Facebook
- **Nguyên nhân**: Token/API key bị hết hạn, sai cấu hình trong file `.env`, hoặc máy chủ bị chặn kết nối ra Internet.
- **Cách xử lý**:
  1. Kiểm tra logs để xem mã lỗi phản hồi từ API nhà cung cấp:
     ```bash
     tail -n 200 logs/error.log
     ```
  2. Xác minh kết nối Internet từ bên trong container:
     ```bash
     docker compose exec pnews-web ping -c 3 google.com
     ```
  3. Kiểm tra lại cấu hình các khóa bảo mật trong file `.env` ngoài máy host và restart lại web container sau khi sửa đổi.
