# Tài liệu Biến Môi trường Cấu hình PNews (Environment Variables)

Hệ thống PNews sử dụng các biến môi trường để nạp cấu hình hệ thống, thông tin tài khoản admin và các khóa API kết nối dịch vụ ngoài. Cấu hình này được nạp tự động từ tệp `.env` ở thư mục gốc của dự án hoặc từ biến môi trường máy host Linux.

---

## 1. Các Biến Môi trường Hệ thống

| Tên biến | Kiểu dữ liệu | Giá trị mặc định | Vai trò / Mô tả | Bắt buộc |
| :--- | :---: | :---: | :--- | :---: |
| `PNEWS_APP_ENV` | String | `production` | Môi trường chạy ứng dụng (`production`, `development`). | Không |
| `PNEWS_HOST` | String | `0.0.0.0` | IP lắng nghe của Web Server. Để là `0.0.0.0` để kết nối được từ ngoài container. | Không |
| `PNEWS_PORT` | Integer | `8000` | Cổng dịch vụ Web lắng nghe bên trong container. | Không |
| `PNEWS_DATA_DIR` | String/Path | `data` | Thư mục lưu trữ database, ảnh news cards và upload. | Không |
| `PNEWS_LOG_DIR` | String/Path | `logs` | Thư mục ghi logs hệ thống. | Không |
| `PNEWS_DATABASE_PATH`| String/Path | `data/cms.sqlite3` | Đường dẫn lưu file Database SQLite. | Không |
| `PNEWS_DOMAIN` | String | Rỗng | Domain public dùng cho Nginx/HTTPS, ví dụ `news.example.com`. | Chỉ khi dùng script Cloudflare |
| `PNEWS_WWW_DOMAIN` | String | Rỗng | Domain phụ tùy chọn, ví dụ `www.news.example.com`. | Không |
| `PNEWS_CERTBOT_EMAIL` | String | Rỗng | Email đăng ký Let's Encrypt/Certbot. | Chỉ khi dùng script Cloudflare |
| `CLOULDFARE_TOKEN` | String | Rỗng | Cloudflare API token dùng cho DNS challenge. Giữ đúng tên biến này theo yêu cầu triển khai. | Chỉ khi dùng script Cloudflare |
| `CLOUDFLARE_API_TOKEN` | String | Rỗng | Alias viết đúng chính tả; script dùng nếu `CLOULDFARE_TOKEN` trống. | Không |
| `CLOUDFLARE_DNS_PROPAGATION_SECONDS` | Integer | `60` | Thời gian chờ DNS propagation trước khi Certbot xác minh. | Không |
| `PNEWS_DISABLE_DEFAULT_NGINX_SITE` | Boolean | `1` | Xóa symlink site mặc định của Nginx khi setup site PNews. | Không |

---

## 2. Cấu hình Tài khoản Quản trị (Admin CMS)

| Tên biến | Kiểu dữ liệu | Định dạng ví dụ | Vai trò / Mô tả | Bắt buộc |
| :--- | :---: | :---: | :--- | :---: |
| `PNEWS_ADMIN_ACCOUNTS`| JSON String | `{"admin":"your_strong_password"}` | Danh sách tài khoản admin CMS dưới dạng JSON key-value. Cho phép cấu hình nhiều tài khoản cùng lúc. | **Có** |

---

## 3. Cấu hình Tự động đăng bài Facebook Page

| Tên biến | Kiểu dữ liệu | Vai trò / Mô tả | Bắt buộc |
| :--- | :---: | :--- | :---: |
| `FACEBOOK_PAGE_ID` | String | ID của Fanpage Facebook nơi đăng ảnh ấn phẩm. | Chỉ khi dùng Facebook |
| `FACEBOOK_PAGE_ACCESS_TOKEN`| String | Access Token có quyền đăng bài đại diện Page (Page Access Token). | Chỉ khi dùng Facebook |
| `FACEBOOK_GRAPH_API_VERSION` | String | Phiên bản Facebook Graph API (Ví dụ: `v25.0`). | Không |

---

## 4. Cấu hình Telegram Notification

| Tên biến | Kiểu dữ liệu | Vai trò / Mô tả | Bắt buộc |
| :--- | :---: | :--- | :---: |
| `TELEGRAM_BOT_TOKEN` | String | HTTP API Token nhận được từ BotFather để gửi thông báo tin tức. | Chỉ khi dùng Telegram |
| `TELEGRAM_CHAT_ID` | String | ID của Channel hoặc Group nhận thông báo tự động. | Chỉ khi dùng Telegram |

---

## 5. Cấu hình Trí tuệ Nhân tạo (AI Summarization)

Hệ thống sử dụng AI để tóm tắt các bài viết bị thiếu tóm tắt gốc từ crawler.

| Tên biến | Kiểu dữ liệu | Vai trò / Mô tả | Bắt buộc |
| :--- | :---: | :--- | :---: |
| `GEMINI_API_KEY` | String | Khóa API để gọi dịch vụ Google Gemini (Mô hình mặc định: `gemini-2.5-flash`). | Không |
| `GROQ_API_KEY` | String | Khóa API để gọi dịch vụ Groq (Mô hình mặc định: `llama-3.1-8b-instant`). | Không |

---

## 6. Mẫu cấu hình `.env` chuẩn Sản xuất (Production)
```ini
PNEWS_APP_ENV=production
PNEWS_HOST=0.0.0.0
PNEWS_PORT=8000
PNEWS_DATA_DIR=data
PNEWS_LOG_DIR=logs
PNEWS_DATABASE_PATH=data/cms.sqlite3

# Domain + HTTPS qua Nginx/Cloudflare
PNEWS_DOMAIN=your-domain.com
PNEWS_WWW_DOMAIN=www.your-domain.com
PNEWS_CERTBOT_EMAIL=admin@your-domain.com
CLOULDFARE_TOKEN=your_cloudflare_dns_api_token
CLOUDFLARE_API_TOKEN=
CLOUDFLARE_DNS_PROPAGATION_SECONDS=60
PNEWS_DISABLE_DEFAULT_NGINX_SITE=1

# Tài khoản Admin đăng nhập CMS
PNEWS_ADMIN_ACCOUNTS={"admin":"replace_with_a_strong_password"}

# Facebook Page Config
FACEBOOK_PAGE_ID=your_facebook_page_id
FACEBOOK_PAGE_ACCESS_TOKEN=your_facebook_page_access_token
FACEBOOK_GRAPH_API_VERSION=v25.0

# Telegram Channel Config
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id

# AI API Keys
GEMINI_API_KEY=your_gemini_api_key
GROQ_API_KEY=your_groq_api_key
```
