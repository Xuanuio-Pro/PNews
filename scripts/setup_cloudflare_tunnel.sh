#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env}"
CLOUDFLARED_ENV="/etc/cloudflared/pnews.env"
CLOUDFLARED_SERVICE="/etc/systemd/system/pnews-cloudflared.service"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

get_env_value() {
    local key="$1"
    local value="${!key:-}"
    if [ -n "$value" ]; then
        printf '%s' "$value"
        return 0
    fi

    if [ ! -f "$ENV_FILE" ]; then
        return 0
    fi

    local line
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%$'\r'}"
        line="${line#"${line%%[![:space:]]*}"}"
        case "$line" in
            ""|\#*) continue ;;
            "$key"=*)
                value="${line#*=}"
                value="${value%"${value##*[![:space:]]}"}"
                value="${value#\"}"
                value="${value%\"}"
                value="${value#\'}"
                value="${value%\'}"
                printf '%s' "$value"
                return 0
                ;;
        esac
    done < "$ENV_FILE"
}

require_value() {
    local name="$1"
    local value="$2"
    if [ -z "$value" ]; then
        echo "Thiếu biến $name trong $ENV_FILE" >&2
        exit 1
    fi
}

cloudflared_download_url() {
    local arch
    arch="$(uname -m)"
    case "$arch" in
        x86_64|amd64)
            echo "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
            ;;
        aarch64|arm64)
            echo "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64"
            ;;
        armv7l|armhf)
            echo "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm"
            ;;
        *)
            echo "Không hỗ trợ kiến trúc máy chủ: $arch" >&2
            exit 1
            ;;
    esac
}

if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
else
    SUDO="sudo"
fi

TUNNEL_TOKEN="$(get_env_value CLOUDFLARE_TUNNEL_TOKEN)"
if [ -z "$TUNNEL_TOKEN" ]; then
    TUNNEL_TOKEN="$(get_env_value CLOULDFARE_TUNNEL_TOKEN)"
fi

HEALTH_URL="$(get_env_value PNEWS_TUNNEL_HEALTH_URL)"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health}"
PUBLIC_HOSTNAME="$(get_env_value PNEWS_TUNNEL_HOSTNAME)"

require_value "CLOUDFLARE_TUNNEL_TOKEN hoặc CLOULDFARE_TUNNEL_TOKEN" "$TUNNEL_TOKEN"

log "Cài gói phụ trợ..."
$SUDO apt-get update
$SUDO apt-get install -y ca-certificates curl

if command -v cloudflared >/dev/null 2>&1; then
    CLOUDFLARED_BIN="$(command -v cloudflared)"
    log "Đã có cloudflared tại $CLOUDFLARED_BIN"
else
    CLOUDFLARED_BIN="/usr/local/bin/cloudflared"
    log "Tải cloudflared vào $CLOUDFLARED_BIN..."
    tmp_cloudflared="$(mktemp)"
    curl -fsSL "$(cloudflared_download_url)" -o "$tmp_cloudflared"
    $SUDO install -m 755 "$tmp_cloudflared" "$CLOUDFLARED_BIN"
    rm -f "$tmp_cloudflared"
fi

log "Đảm bảo pnews-web đang chạy..."
cd "$PROJECT_DIR"
docker compose up -d --build pnews-web

log "Kiểm tra web app nội bộ: $HEALTH_URL"
if ! curl -fsS "$HEALTH_URL" >/dev/null; then
    echo "pnews-web chưa phản hồi tại $HEALTH_URL" >&2
    docker compose ps
    exit 1
fi

log "Ghi Tunnel token vào /etc/cloudflared/pnews.env"
tmp_env="$(mktemp)"
printf 'CLOUDFLARE_TUNNEL_TOKEN=%s\n' "$TUNNEL_TOKEN" > "$tmp_env"
$SUDO install -d -m 700 /etc/cloudflared
$SUDO install -m 600 "$tmp_env" "$CLOUDFLARED_ENV"
rm -f "$tmp_env"

log "Tạo systemd service pnews-cloudflared..."
tmp_service="$(mktemp)"
cat > "$tmp_service" <<EOF
[Unit]
Description=PNews Cloudflare Tunnel
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=$CLOUDFLARED_ENV
ExecStart=$CLOUDFLARED_BIN tunnel --no-autoupdate run --token \${CLOUDFLARE_TUNNEL_TOKEN}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

$SUDO install -m 644 "$tmp_service" "$CLOUDFLARED_SERVICE"
rm -f "$tmp_service"

log "Khởi động Cloudflare Tunnel service..."
$SUDO systemctl daemon-reload
$SUDO systemctl enable pnews-cloudflared
$SUDO systemctl restart pnews-cloudflared
sleep 3

if ! $SUDO systemctl is-active --quiet pnews-cloudflared; then
    echo "pnews-cloudflared chưa chạy ổn định. Log gần nhất:" >&2
    $SUDO journalctl -u pnews-cloudflared -n 50 --no-pager >&2
    exit 1
fi

log "Cloudflare Tunnel đang chạy."
if [ -n "$PUBLIC_HOSTNAME" ]; then
    echo "Kiểm tra public hostname:"
    echo "  curl -I https://$PUBLIC_HOSTNAME/health"
    echo "  curl -I https://$PUBLIC_HOSTNAME/client"
    echo "  curl -I https://$PUBLIC_HOSTNAME/admin"
else
    echo "Hãy kiểm tra Public Hostname đã cấu hình trong Cloudflare Zero Trust trỏ về http://127.0.0.1:8000."
fi

echo "Xem log:"
echo "  sudo journalctl -u pnews-cloudflared -f"
