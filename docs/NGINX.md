# Cấu hình Nginx cho PNews

Tài liệu này dùng để cấu hình Nginx làm reverse proxy từ domain public vào web app PNews đang chạy bằng Docker Compose tại `127.0.0.1:8000`.

Nếu bạn muốn dùng Cloudflare Tunnel thay vì Nginx public port, xem `docs/CLOUDFLARE_TUNNEL.md`.

## 1. Điều kiện trước

- Docker service `pnews-web` đã chạy:

```bash
cd /opt/pnews
docker compose up -d --build pnews-web
curl http://127.0.0.1:8000/health
```

- Domain đã trỏ DNS A/AAAA về IP server.
- Firewall mở HTTP/HTTPS:

```bash
sudo ufw allow 'Nginx Full'
```

## 2. Cài Nginx

```bash
sudo apt update
sudo apt install -y nginx
sudo systemctl enable nginx
sudo systemctl start nginx
```

## 3. Tạo site PNews

Copy file mẫu:

```bash
sudo cp /opt/pnews/deploy/nginx/pnews.conf.example /etc/nginx/sites-available/pnews
sudo nano /etc/nginx/sites-available/pnews
```

Sửa dòng `server_name` thành domain thật, ví dụ:

```nginx
server_name news.example.com www.news.example.com;
```

Bật site:

```bash
sudo ln -s /etc/nginx/sites-available/pnews /etc/nginx/sites-enabled/pnews
sudo nginx -t
sudo systemctl reload nginx
```

Kiểm tra:

```bash
curl -I http://news.example.com/health
curl -I http://news.example.com/client
curl -I http://news.example.com/admin
```

## 4. Cấu hình HTTPS bằng Certbot

### Cách tự động bằng Cloudflare token

Nếu DNS của domain đang dùng Cloudflare, cách khuyến nghị là dùng script có sẵn:

```bash
cd /opt/pnews
nano .env
```

Điền các biến sau:

```ini
PNEWS_DOMAIN=news.example.com
PNEWS_WWW_DOMAIN=www.news.example.com
PNEWS_CERTBOT_EMAIL=admin@example.com
CLOULDFARE_TOKEN=your_cloudflare_dns_api_token
```

Token Cloudflare cần quyền tối thiểu:

- `Zone:Read`
- `DNS:Edit`
- Giới hạn trong đúng zone/domain của PNews.

Trong Cloudflare Dashboard, nên đặt SSL/TLS mode là `Full (strict)` sau khi script cấp chứng chỉ thành công.

Sau đó chạy:

```bash
chmod +x scripts/setup_nginx_cloudflare.sh
./scripts/setup_nginx_cloudflare.sh
```

Script sẽ tự:

- Cài `nginx`, `certbot`, `python3-certbot-dns-cloudflare`.
- Build/chạy `pnews-web`.
- Tạo credentials riêng tại `/etc/letsencrypt/cloudflare-pnews.ini` với quyền `600`.
- Lấy SSL certificate bằng DNS challenge Cloudflare.
- Render file Nginx HTTPS từ `deploy/nginx/pnews-cloudflare-ssl.conf.template`.
- Reload Nginx.

Kiểm tra:

```bash
curl -I https://news.example.com/health
curl -I https://news.example.com/client
curl -I https://news.example.com/admin
```

### Cách thủ công bằng plugin Nginx

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d news.example.com -d www.news.example.com
sudo nginx -t
sudo systemctl reload nginx
```

Certbot sẽ tự thêm block SSL và redirect HTTP sang HTTPS. Không cần tự sửa certificate path nếu dùng lệnh trên.

## 5. Lệnh vận hành nhanh

```bash
sudo nginx -t
sudo systemctl status nginx
sudo systemctl reload nginx
sudo tail -n 100 -f /var/log/nginx/pnews_access.log
sudo tail -n 100 -f /var/log/nginx/pnews_error.log
```

Nếu Nginx trả `502 Bad Gateway`, kiểm tra web app:

```bash
cd /opt/pnews
docker compose ps
docker logs -f pnews_web
curl http://127.0.0.1:8000/health
```
