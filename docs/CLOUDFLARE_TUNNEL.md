# Kết nối PNews qua Cloudflare Tunnel

Cloudflare Tunnel cho phép public website PNews mà không cần mở port `80/443` trực tiếp vào VPS. Tunnel connector chạy trên VPS và nối Cloudflare vào web app nội bộ tại `127.0.0.1:8000`.

## 1. Tạo Tunnel token trên Cloudflare

Trong Cloudflare Zero Trust:

1. Vào `Networks` -> `Tunnels`.
2. Tạo tunnel mới, chọn connector `cloudflared`.
3. Chọn kiểu cài đặt bằng token.
4. Copy tunnel token.
5. Trong phần `Public Hostname`, trỏ domain về service:

```text
Service type: HTTP
URL: http://127.0.0.1:8000
```

Ví dụ:

```text
Hostname: news.example.com
Service: http://127.0.0.1:8000
```

## 2. Điền `.env` trên VPS

```bash
cd /opt/pnews
nano .env
```

Thêm hoặc cập nhật:

```ini
PNEWS_TUNNEL_HOSTNAME=news.example.com
PNEWS_TUNNEL_HEALTH_URL=http://127.0.0.1:8000/health
CLOUDFLARE_TUNNEL_TOKEN=your_cloudflare_tunnel_token
```

Script cũng hỗ trợ alias `CLOULDFARE_TUNNEL_TOKEN` nếu bạn muốn giữ cách viết `CLOULDFARE`.

Lưu ý: `CLOUDFLARE_TUNNEL_TOKEN` là token tunnel connector, khác với `CLOULDFARE_TOKEN` dùng cho Certbot DNS challenge.

## 3. Chạy setup

```bash
cd /opt/pnews
git pull
chmod +x scripts/setup_cloudflare_tunnel.sh
./scripts/setup_cloudflare_tunnel.sh
```

Script sẽ tự:

- Cài `cloudflared` vào `/usr/local/bin/cloudflared` nếu chưa có.
- Build/chạy `pnews-web`.
- Kiểm tra `http://127.0.0.1:8000/health`.
- Tạo file token root-only tại `/etc/cloudflared/pnews.env`.
- Tạo systemd service `pnews-cloudflared`.
- Enable và start tunnel.

## 4. Kiểm tra

```bash
sudo systemctl status pnews-cloudflared
sudo journalctl -u pnews-cloudflared -f
curl -I https://news.example.com/health
curl -I https://news.example.com/client
curl -I https://news.example.com/admin
```

Nếu Cloudflare báo lỗi, kiểm tra:

```bash
cd /opt/pnews
docker compose ps
curl http://127.0.0.1:8000/health
sudo journalctl -u pnews-cloudflared -n 100 --no-pager
```

## 5. Cập nhật token tunnel

Nếu đổi token trên Cloudflare:

```bash
cd /opt/pnews
nano .env
./scripts/setup_cloudflare_tunnel.sh
```

Script sẽ ghi lại token và restart service.
