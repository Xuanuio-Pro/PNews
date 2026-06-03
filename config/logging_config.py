import logging
import logging.handlers
from pathlib import Path
from config.settings import LOG_DIR

# Đảm bảo thư mục log tồn tại
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Format log: timestamp, level, name, filename, line number, message
LOG_FORMAT = "[%(asctime)s] %(levelname)s %(name)s (%(filename)s:%(lineno)d): %(message)s"
formatter = logging.Formatter(LOG_FORMAT)

def setup_logging(log_filename="app.log"):
    """
    Cấu hình hệ thống ghi log tập trung.
    Ghi log ra console, file nhật ký chuyên biệt, và file tổng hợp lỗi logs/error.log.
    """
    root_logger = logging.getLogger()
    
    # Tránh gắn lặp handlers nếu đã được cấu hình trước đó
    if root_logger.hasHandlers():
        return
        
    root_logger.setLevel(logging.INFO)
    
    # Handler xuất log ra console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)
    
    # Handler lưu log riêng biệt (app.log hoặc crawler.log)
    file_path = LOG_DIR / log_filename
    file_handler = logging.handlers.RotatingFileHandler(
        file_path, maxBytes=10*1024*1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    
    # Handler lưu các cảnh báo/lỗi nghiêm trọng vào logs/error.log
    error_path = LOG_DIR / "error.log"
    error_handler = logging.handlers.RotatingFileHandler(
        error_path, maxBytes=10*1024*1024, backupCount=5, encoding="utf-8"
    )
    error_handler.setFormatter(formatter)
    error_handler.setLevel(logging.WARNING) # Chỉ ghi nhận WARNING, ERROR, CRITICAL
    root_logger.addHandler(error_handler)
