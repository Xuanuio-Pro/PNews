#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env}"
NGINX_TEMPLATE="$PROJECT_DIR/deploy/nginx/pnews-cloudflare-ssl.conf.template"
NGINX_SITE="/etc/nginx/sites-available/pnews"
NGINX_ENABLED="/etc/nginx/sites-enabled/pnews"
CLOUDFLARE_CREDENTIALS="/etc/letsencrypt/cloudflare-pnews.ini"

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

if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
else
    SUDO="sudo"
fi

DOMAIN="$(get_env_value PNEWS_DOMAIN)"
WWW_DOMAIN="$(get_env_value PNEWS_WWW_DOMAIN)"
EMAIL="$(get_env_value PNEWS_CERTBOT_EMAIL)"
CF_TOKEN="$(get_env_value CLOULDFARE_TOKEN)"
if [ -z "$CF_TOKEN" ]; then
    CF_TOKEN="$(get_env_value CLOUDFLARE_API_TOKEN)"
fi
PROPAGATION_SECONDS="$(get_env_value CLOUDFLARE_DNS_PROPAGATION_SECONDS)"
PROPAGATION_SECONDS="${PROPAGATION_SECONDS:-60}"

require_value "PNEWS_DOMAIN" "$DOMAIN"
require_value "PNEWS_CERTBOT_EMAIL" "$EMAIL"
require_value "CLOULDFARE_TOKEN" "$CF_TOKEN"

SERVER_NAMES="$DOMAIN"
CERTBOT_DOMAINS=(-d "$DOMAIN")
if [ -n "$WWW_DOMAIN" ]; then
    SERVER_NAMES="$SERVER_NAMES $WWW_DOMAIN"
    CERTBOT_DOMAINS+=(-d "$WWW_DOMAIN")
fi

log "Cài hoặc cập nhật Nginx, Certbot và plugin Cloudflare..."
$SUDO apt-get update
$SUDO apt-get install -y curl nginx certbot python3-certbot-dns-cloudflare

log "Đảm bảo pnews-web đang chạy..."
cd "$PROJECT_DIR"
docker compose up -d --build pnews-web

log "Kiểm tra web app nội bộ..."
if ! curl -fsS http://127.0.0.1:8000/health >/dev/null; then
    echo "pnews-web chưa phản hồi tại http://127.0.0.1:8000/health" >&2
    docker compose ps
    exit 1
fi

log "Ghi Cloudflare token vào file credentials riêng của Certbot..."
tmp_credentials="$(mktemp)"
printf 'dns_cloudflare_api_token = %s\n' "$CF_TOKEN" > "$tmp_credentials"
$SUDO install -d -m 700 /etc/letsencrypt
$SUDO install -m 600 "$tmp_credentials" "$CLOUDFLARE_CREDENTIALS"
rm -f "$tmp_credentials"

log "Lấy hoặc gia hạn SSL certificate bằng DNS challenge Cloudflare..."
$SUDO certbot certonly \
    --dns-cloudflare \
    --dns-cloudflare-credentials "$CLOUDFLARE_CREDENTIALS" \
    --dns-cloudflare-propagation-seconds "$PROPAGATION_SECONDS" \
    --email "$EMAIL" \
    --agree-tos \
    --non-interactive \
    --keep-until-expiring \
    "${CERTBOT_DOMAINS[@]}"

log "Render Nginx HTTPS site..."
tmp_nginx="$(mktemp)"
sed \
    -e "s/__SERVER_NAMES__/$SERVER_NAMES/g" \
    -e "s/__PRIMARY_DOMAIN__/$DOMAIN/g" \
    "$NGINX_TEMPLATE" > "$tmp_nginx"

$SUDO install -m 644 "$tmp_nginx" "$NGINX_SITE"
rm -f "$tmp_nginx"
$SUDO ln -sfn "$NGINX_SITE" "$NGINX_ENABLED"

if [ "$(get_env_value PNEWS_DISABLE_DEFAULT_NGINX_SITE)" != "0" ]; then
    $SUDO rm -f /etc/nginx/sites-enabled/default
fi

log "Kiểm tra và reload Nginx..."
$SUDO nginx -t
$SUDO systemctl enable nginx
$SUDO systemctl reload nginx

log "Hoàn tất. Kiểm tra:"
echo "  curl -I https://$DOMAIN/health"
echo "  curl -I https://$DOMAIN/client"
echo "  curl -I https://$DOMAIN/admin"
