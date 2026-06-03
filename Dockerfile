FROM python:3.11-slim

# Thiết lập các biến môi trường cấu hình chạy Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1

WORKDIR /app

# Cài đặt fonts và fontconfig hệ thống để Pillow hiển thị tiếng Việt chính xác
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    fontconfig \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Cài đặt Python packages trước để tận dụng cache của Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Sao chép toàn bộ mã nguồn
COPY . .

# Cấp quyền thực thi cho entrypoint script và các script khác
RUN chmod +x entrypoint.sh scripts/*.sh 2>/dev/null || true

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]

# CMD mặc định cho Service Web
CMD ["python", "web_app.py", "--host", "0.0.0.0", "--port", "8000"]
