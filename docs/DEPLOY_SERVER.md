# Hướng dẫn Triển khai Hệ thống PNews trên Linux Server (Ubuntu)

Tài liệu này hướng dẫn chi tiết quy trình cài đặt, triển khai và vận hành hệ thống PNews trên máy chủ Linux/VPS (khuyên dùng Ubuntu 20.04 LTS hoặc 22.04 LTS).

---

## 1. Yêu cầu hệ thống tối thiểu
- **Hệ điều hành**: Ubuntu Server 20.04 LTS / 22.04 LTS hoặc các bản phân phối Linux tương thích Debian.
- **CPU**: 1 Core trở lên.
- **RAM**: Tối thiểu 1 GB (Khuyên dùng 2 GB để build Docker mượt mà).
- **Bộ nhớ**: Tối thiểu 10 GB SSD trống.
- **Phần mềm**: Docker, Docker Compose.

---

## 2. Cài đặt Docker và Docker Compose trên Ubuntu
Chạy các lệnh sau dưới quyền `root` hoặc user có quyền `sudo` để cấu hình Docker:

```bash
# Cập nhật danh sách gói hệ thống
sudo apt-get update

# Cài đặt các gói phụ trợ cần thiết
sudo apt-get install -y apt-transport-https ca-certificates curl software-properties-common gnupg lsb-release

# Thêm khóa GPG chính thức của Docker
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# Thêm Docker Repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Cập nhật lại apt và cài đặt Docker Engine + Docker Compose Plugin
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Khởi động và cấu hình Docker tự động chạy cùng hệ thống
sudo systemctl enable docker
sudo systemctl start docker
```

---

## 3. Clone Repository và Cấu hình Thư mục
Khuyên dùng vị trí cài đặt chuẩn `/opt/pnews`:

```bash
# Tạo thư mục và thiết lập quyền sở hữu
sudo mkdir -p /opt/pnews
sudo chown -R $USER:$USER /opt/pnews

# Clone mã nguồn dự án vào thư mục
git clone <URL_REPOSITORY_CUA_BAN> /opt/pnews
cd /opt/pnews
```

---

## 4. Cấu hình biến môi trường `.env`
Sao chép cấu hình mẫu từ `.env.example`:

```bash
cp .env.example .env
```

Mở file `.env` bằng trình soạn thảo (ví dụ: `nano .env`) và khai báo thông tin thực tế:
- `PNEWS_ADMIN_ACCOUNTS`: JSON quy định tài khoản đăng nhập admin.
- `FACEBOOK_PAGE_ACCESS_TOKEN`, `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`, `GROQ_API_KEY`, ...

---

## 5. Build và Chạy Dịch vụ Web CMS
Chạy dịch vụ web nền bằng Docker Compose:

```bash
# Build Docker image và khởi chạy dịch vụ
docker compose up -d --build pnews-web

# Kiểm tra trạng thái các container đang chạy
docker compose ps

# Theo dõi nhật ký chạy (logs) của dịch vụ Web
docker logs -f pnews_web
```

Truy cập kiểm tra trạng thái sức khỏe (Healthcheck):
```bash
curl http://localhost:8000/health
```

---

## 6. Cấu hình Nginx reverse proxy
Sau khi `pnews-web` chạy ổn định trên cổng `8000`, có thể dùng Nginx để đưa website ra domain public:

```bash
sudo apt update
sudo apt install -y nginx
sudo cp /opt/pnews/deploy/nginx/pnews.conf.example /etc/nginx/sites-available/pnews
sudo nano /etc/nginx/sites-available/pnews
sudo ln -s /etc/nginx/sites-available/pnews /etc/nginx/sites-enabled/pnews
sudo nginx -t
sudo systemctl reload nginx
```

Trong file Nginx, thay `pnews.example.com` bằng domain thật. Xem hướng dẫn chi tiết tại `docs/NGINX.md`.

---

## 7. Kiểm tra chạy thử Crawler thủ công
Để đảm bảo môi trường container chạy tốt, hãy kiểm tra crawler:

```bash
docker compose run --rm pnews-crawler
```

Nếu crawler chạy xong và lưu dữ liệu thành công mà không báo lỗi, môi trường đã sẵn sàng hoạt động.

---

## 8. Cấu hình Múi giờ hệ thống và Lập lịch Cron chạy tự động lúc 7:00 Sáng
Để đảm bảo logs ghi nhận đúng thời gian Việt Nam và crawler kích hoạt đúng 7h sáng giờ Hà Nội:

```bash
# Thiết lập múi giờ hệ thống máy chủ về Asia/Ho_Chi_Minh
sudo timedatectl set-timezone Asia/Ho_Chi_Minh
```

Cấp quyền thực thi cho các file script vận hành:
```bash
chmod +x /opt/pnews/scripts/*.sh
```

Mở tệp lập lịch cron của hệ thống:
```bash
crontab -e
```

Thêm dòng sau vào cuối file để hệ thống tự động chạy crawler lúc 07:00 hàng ngày:
```text
0 7 * * * /opt/pnews/scripts/run_crawler_server.sh >> /opt/pnews/logs/cron_crawler.log 2>&1
```

---

## 9. Quy trình Cập nhật Phiên bản mới (Update Code)
Khi có sự thay đổi về mã nguồn trên GitHub, tiến hành update như sau:

```bash
cd /opt/pnews

# Kéo mã nguồn mới nhất về
git pull

# Build lại container và khởi chạy lại dịch vụ web không làm ngắt quãng
docker compose up -d --build pnews-web
```

---

## 10. Rollback cơ bản khi gặp sự cố cập nhật
Nếu phiên bản mới bị lỗi hoặc không khởi động được, có thể khôi phục nhanh về bản ổn định trước đó:

```bash
# Quay lại commit ổn định trước
git checkout <ma_hash_commit_on_dinh>

# Build và khởi chạy lại dịch vụ
docker compose up -d --build pnews-web
```
*Lưu ý: Dữ liệu bài viết trong thư mục `data/` được mount ra ngoài nên sẽ được bảo toàn nguyên vẹn, không bị mất mát khi rollback code.*
