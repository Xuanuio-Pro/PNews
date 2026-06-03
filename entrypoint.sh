#!/bin/sh
set -e

# Đảm bảo các thư mục dữ liệu và logs luôn tồn tại khi khởi chạy container
mkdir -p data/raw data/exports data/generated_images data/thumbnails logs backups data/uploads data/master

# Thực thi lệnh CMD từ Dockerfile hoặc docker-compose
exec "$@"
