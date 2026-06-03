# Cấu hình Nginx cho PNews

Tài liệu này dùng để cấu hình Nginx làm reverse proxy từ domain public vào web app PNews đang chạy bằng Docker Compose tại `127.0.0.1:8000`.

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
