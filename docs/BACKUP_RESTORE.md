# Hướng dẫn Sao lưu và Khôi phục Dữ liệu PNews (Backup & Restore)

Tài liệu này hướng dẫn cách sao lưu cơ sở dữ liệu SQLite, ảnh News Cards, cấu hình logs và khôi phục hệ thống khi xảy ra sự cố phần cứng hoặc di chuyển máy chủ.

---

## 1. Cơ chế Sao lưu Dữ liệu (Backup)

Dự án cung cấp sẵn script `scripts/backup_data.sh` tự động đóng gói toàn bộ dữ liệu quan trọng bao gồm:
- Cơ sở dữ liệu SQLite (`data/cms.sqlite3`).
- Ảnh thiết kế News Cards (`data/generated_images/`).
- Ảnh admin tải lên thủ công (`data/uploads/`).
- Master CSV bài viết đã crawl để chống trùng (`data/master/`).
- CSV exports phục vụ tải bài (`data/exports/`).
- Toàn bộ logs hệ thống (`logs/`).

### Chạy sao lưu thủ công
Chạy script sao lưu tại thư mục dự án:
```bash
./scripts/backup_data.sh
```
Sau khi chạy xong, file sao lưu dạng `pnews_backup_YYYY-MM-DD_HH-mm.tar.gz` sẽ nằm tại thư mục `/opt/pnews/backups/` và log tiến trình được ghi vào `logs/backup.log`.

---

## 2. Cấu hình tự động sao lưu hàng ngày bằng Cron

Để đảm bảo an toàn thông tin, nên thiết lập sao lưu tự động hàng ngày lúc 2h sáng (thời điểm hệ thống ít người truy cập):

1. Mở danh sách cron của hệ thống:
   ```bash
   crontab -e
   ```
2. Thêm dòng cấu hình lập lịch sau:
   ```text
   0 2 * * * /opt/pnews/scripts/backup_data.sh >> /opt/pnews/logs/backup_cron.log 2>&1
   ```
3. Lưu và thoát. Hệ thống sẽ tự động dọn dẹp và chỉ lưu giữ 14 bản backup mới nhất để tránh đầy ổ đĩa.

---

## 3. Quy trình Khôi phục Dữ liệu (Restore)

Dự án cung cấp sẵn script `scripts/restore_data.sh` để phục hồi dữ liệu từ file nén dự phòng. 

> [!CAUTION]
> Tiến trình khôi phục sẽ ghi đè toàn bộ dữ liệu hiện tại trong thư mục `data/` và `logs/`. Hãy chắc chắn rằng bạn chọn đúng tệp tin backup mong muốn.

### Các bước khôi phục dữ liệu:
1. Xác định file nén backup cần phục hồi tại thư mục `backups/` (ví dụ: `backups/pnews_backup_2026-06-03_14-30.tar.gz`).
2. Chạy lệnh restore với đường dẫn file nén làm đối số:
   ```bash
   ./scripts/restore_data.sh backups/pnews_backup_2026-06-03_14-30.tar.gz
   ```
3. Script sẽ tự động thực hiện:
   - Dừng container dịch vụ Web `pnews-web`.
   - Tạo một bản nén dự phòng khẩn cấp cho dữ liệu hiện tại (lưu tại `backups/pre_restore_backup_...tar.gz`) để có thể rollback nếu restore lỗi.
   - Giải nén ghi đè tệp tin backup vào thư mục dự án.
   - Khởi động lại dịch vụ Web `pnews-web`.

Xác minh hoạt động của dịch vụ sau khi khôi phục:
```bash
curl http://localhost:8000/health
```

---

## 4. Lưu ý bảo mật quan trọng với `.env`

- **Không đưa file `.env` vào bản backup chung**: Tệp tin cấu hình môi trường `.env` chứa mật khẩu quản trị và token kết nối nhạy cảm. Nó đã được đưa vào danh sách `.dockerignore` và `.gitignore` để tránh bị lộ.
- **Sao lưu `.env` riêng biệt**: Hãy lưu trữ file `.env` ở một kho lưu trữ bảo mật bên ngoài (ví dụ: password manager) của riêng bạn. Khi khôi phục hệ thống sang một máy chủ hoàn toàn mới, bạn chỉ cần tạo lại file `.env` này trước khi tiến hành restore dữ liệu nén.
