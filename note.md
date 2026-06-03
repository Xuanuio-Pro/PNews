# Project Notes

File nay ghi lai trang thai va cac viec da lam trong project. README dung cho huong dan su dung, con file nay dung nhu nhat ky tien do.

## 2026-05-20

### Da hoan thanh

- Xay dung crawler theo chuyen muc cho 3 nguon: VNExpress, Dan tri va 24h.
- Chuan hoa du lieu dau ra voi cac truong: `source`, `title`, `url`, `crawled_at`, `thumbnail`, `summary`, `summary_source`, `newspaper_type`, `content_topic`, `category`.
- Sua luong luu CSV de tu tao thu muc `data` khi can.
- To chuc output theo cac thu muc `data/raw`, `data/exports`, `data/processed`, `data/daily/YYYY-MM-DD`, `data/master`, `data/generated_images`, `data/thumbnails`, `data/summaries`.
- Them `master_articles.csv` de nhan dien bai moi va tranh xu ly trung giua cac ngay.
- Tao batch `run_crawler.bat` de chay pipeline hang ngay: crawl, enrich summary, tao news card va ghi log.
- Them dashboard web voi man hinh client/admin, hang doi duyet bai, upload bai va dashboard tong quan.

### Can lam tiep cho v2.0

- Tach cau hinh moi truong ro rang hon, uu tien `.env` hoac bien moi truong khi deploy.
- Them test tu dong cho crawler, storage va API.
- Bo sung lich chay crawler tu dong.
- Cai thien auth/admin, khong dung mat khau mac dinh khi deploy.
- Dong goi huong dan deploy va backup database.

## 2026-05-26

### Nâng cấp crawler v2.0

- Đã giới hạn nguồn crawl còn VNExpress, Báo Chính phủ và PTIT.
- Đã sửa crawler VNExpress để chỉ crawl 2 chuyên mục: Khoa học - Công nghệ và Giáo dục.
- Đã thêm crawler Báo Chính phủ cho chuyên mục Khoa giáo / Khoa học công nghệ.
- Đã thêm crawler PTIT cho trang Tin tức chung.
- Đã bỏ Dân trí và 24h khỏi pipeline chính trong `main.py`.
- Dữ liệu vẫn dùng cùng format cũ: `source`, `title`, `url`, `crawled_at`, `thumbnail`, `summary`, `summary_source`, `newspaper_type`, `content_topic`, `category`.
- Web admin/client, enrich summary, generate news card, master_articles, daily snapshot và Telegram notification tiếp tục dùng chung format để không bị phá.

### Bổ sung ngày đăng, phân trang và trạng thái duyệt

- Đã thêm trường `published_at` tương ứng nhãn hiển thị "Ngày đăng" vào dữ liệu crawl, CSV, JSON, master, daily snapshot và SQLite CMS.
- Crawler lấy ngày đăng từ metadata/time trên trang bài viết; nếu không lấy được thì fallback theo thời điểm crawl để không thiếu dữ liệu sắp xếp.
- Web admin/client đã sắp xếp ưu tiên theo `published_at`, sau đó mới tới `crawled_at`.
- Web client và admin đã có phân trang để theo dõi danh sách bài dễ hơn.
- SQLite CMS tự migration thêm `published_at` và `approved_at` khi web app khởi động.
- `master_articles.csv` được bổ sung metadata mới theo URL, nên các bài đã có sẵn trong master vẫn nhận được `published_at` khi crawl lại.
- Admin hiển thị các mốc ngày: Ngày đăng, Crawl, Cập nhật, Duyệt ngày, Từ chối ngày và Xóa ngày tùy trạng thái bài viết.
- Khi admin duyệt bài, bài chuyển sang client như trước và hệ thống mặc định gọi Telegram để đẩy bài sang group đã cấu hình.
- Không cập nhật Git theo yêu cầu; chỉ ghi lại thay đổi trong `note.md`.

## 2026-05-27

### Sửa luồng tạo ấn phẩm và hiển thị ảnh

- Đã chuẩn hóa `services/image_generator.py` để tạo news card 1080 x 1350 px bằng Pillow.
- Hàm chính hiện tại là `generate_news_card(article, output_dir="data/generated_images")`.
- Thumbnail hỗ trợ URL online và file local, resize theo cover + center crop để không méo ảnh.
- Khi thumbnail rỗng/lỗi/timeout/ảnh hỏng, hệ thống fallback về ảnh `PNews.png` và không làm crash pipeline.
- Title được giới hạn tối đa 3 dòng, summary tối đa 5 dòng, nguồn nằm góc dưới phải.
- Đã thêm script `scripts/test_generate_news_cards.py` để tạo thử 3-5 ảnh từ CSV/JSON hiện có, không cần API key và không cần crawl mới.

### Sửa admin/client

- Admin vẫn giữ 3 trang: tổng quan, duyệt bài và tải ấn phẩm.
- Mỗi trang admin có 3 nút nhanh tới các trang còn lại gồm cả client.
- Đã bỏ nút mở bài riêng trong admin; click vào ảnh ấn phẩm, tiêu đề, tóm tắt hoặc link `Bài gốc` sẽ mở đúng URL bài báo.
- Khi duyệt nhiều bài, web hiển thị trạng thái đang xử lý để tránh cảm giác bị treo.
- Duyệt bài được ưu tiên chạy ổn định trước; Telegram notification được đẩy nền để giảm thời gian chờ của admin.
- Client có 3 nút lọc nhanh: `Tin mới nhất`, `Tin tức chung`, `Tin tức PTIT`.
- Danh sách bài đã duyệt sắp xếp bài mới lên trước; nếu cùng ngày thì ưu tiên tin PTIT.
- Đã kiểm tra lại ảnh đã duyệt theo nguồn: Báo Chính phủ, VNExpress và PTIT đều có file ảnh trong `data/generated_images/`.

### Dọn dẹp project

- Đã rà soát file runtime để tránh xóa nhầm dữ liệu crawler, SQLite, CSV/JSON hoặc ảnh đang được web tham chiếu.
- Chỉ dọn nhóm an toàn: cache Python, log rỗng và ảnh test/compat không được SQLite tham chiếu.
- `.gitignore` hiện đã bỏ qua virtualenv, log, cache Python, dữ liệu crawl, thumbnail cache và news card runtime.

### Kiểm tra lịch tự động 7h sáng

- Windows Task Scheduler có task chính `Detai1 News Crawler`, enabled, chạy hằng ngày lúc 07:00.
- Lần chạy gần nhất ghi nhận `Last Run Time: 2026-05-27 07:00:01`, `Last Result: 0`.
- Dữ liệu ngày `data/daily/2026-05-27` được tạo lúc 07:01, xác nhận phần crawl vẫn hoạt động.
- Phát hiện task trùng `Vietnamese News Crawler` cũng chạy cùng `run_crawler.bat` lúc 07:00, đã disable để tránh chạy trùng.
- Đã thêm `scripts/sync_cms_from_csv.py` và cập nhật `run_crawler.bat` để sau khi crawl/enrich/tạo ảnh xong sẽ sync `data/exports/articles.csv` vào `data/cms.sqlite3`.
- Từ lần chạy 07:00 tiếp theo, web admin/client sẽ nhận bài mới qua SQLite mà không cần restart server.
