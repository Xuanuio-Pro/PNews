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
