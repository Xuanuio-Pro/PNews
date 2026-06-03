# Vietnamese News Crawler v2.1

Du an crawl tin tuc phu hop voi dinh huong PNews/PTIT, chuan hoa du lieu, tao anh news card va phuc vu dashboard web admin/client.

## Tinh nang chinh

- Crawl tin theo nguon v2.0: VNExpress, Bao Chinh phu va PTIT.
- Chuan hoa du lieu bai viet theo format cu de khong pha web admin/client.
- Luu raw JSON, CSV exports, master articles chong trung, daily snapshot va processed theo source/topic/category.
- Tao anh news card bang Pillow voi logo `PNews`, fallback ve anh `PNews.png` neu bai viet thieu thumbnail.
- Ho tro enrich summary bang Gemini/Groq/fallback neu summary crawler con thieu.
- Ho tro dashboard web admin/client va Telegram notification nhu phien ban cu.
- Web admin co 3 trang chinh: tong quan, duyet bai va tai an pham; moi trang co nut dieu huong nhanh toi cac trang con lai.
- Web admin/client co bo loc ngay mac dinh hom nay, khong cho chon ngay tuong lai va co nut xem tat ca ngay.
- Admin co the export PNG cho tung bai da duyet hoac cac bai da chon; nut export chi bat khi da tick bai.
- Web client co 3 bo loc nhanh: `Tin moi nhat`, `Tin tuc chung` va `Tin tuc PTIT`.

## Diem moi v2.1

- Doi nhan dien news card ve `PNews` va regenerate lai toan bo an pham hien co.
- Them loc theo ngay cho admin va client; URL ngay tuong lai se tu dong clamp ve ngay hien tai.
- Bo nut tim thu cong trong cac filter auto-submit de giao dien gon hon.
- Them export PNG cho bai da duyet va khoa nut export bulk khi chua chon bai.
- Don dep ignore runtime SQLite WAL/SHM de tranh day file tam len GitHub.

## Nguồn dữ liệu v2.0

VNExpress:

- Khoa học - Công nghệ: `https://vnexpress.net/khoa-hoc-cong-nghe`
- Giáo dục: `https://vnexpress.net/giao-duc`

Báo Chính phủ:

- Khoa giáo / Khoa học công nghệ: `https://baochinhphu.vn/khoa-giao/khoa-hoc-cong-nghe.htm`

PTIT:

- Tin tức - sự kiện / Tin tức chung: `https://ptit.edu.vn/tin-tuc-su-kien/tin-tuc/tin-tuc-chung/`

Nguồn cũ đã tạm ngừng trong pipeline chính:

- Dân trí
- 24h
- Các chuyên mục VNExpress ngoài Khoa học - Công nghệ và Giáo dục

Code crawler cu van duoc giu lai de tham khao, nhung `main.py` khong goi trong pipeline v2.0.

## Truong du lieu chuan

Moi bai viet sau khi crawl co cac cot:

```text
source, title, url, crawled_at, published_at, thumbnail, summary,
summary_source, newspaper_type, content_topic, category
```

Metadata co dinh theo nguon:

- VNExpress: `source = "VNExpress"`, `newspaper_type = "Báo điện tử"`, `category` theo chuyên mục.
- Báo Chính phủ: `source = "Báo Chính phủ"`, `newspaper_type = "Cổng thông tin Chính phủ"`, `category = "Khoa giáo - Khoa học công nghệ"`.
- PTIT: `source = "PTIT"`, `newspaper_type = "Trang tin trường đại học"`, `category = "Tin tức chung"`.

`content_topic` v2.0:

- VNExpress Khoa học - Công nghệ: `Khoa học - Công nghệ`
- VNExpress Giáo dục: `Giáo dục`
- Báo Chính phủ: `Khoa học - Giáo dục`
- PTIT: `Tin tức PTIT`

## Cau truc thu muc

```text
Code/
|-- main.py
|-- web_app.py
|-- run_crawler.bat
|-- requirements.txt
|-- .env.example
|-- config/
|   |-- settings.py
|   `-- logging_config.py
|-- crawlers/
|   |-- base.py
|   |-- vnexpress.py
|   |-- baochinhphu.py
|   |-- ptit.py
|   |-- dantri.py
|   `-- news24h.py
|-- services/
|   |-- storage.py
|   |-- classifier.py
|   |-- article_enricher.py
|   |-- image_generator.py
|   |-- notification_service.py
|   `-- notifiers/
|-- templates/
|-- web_assets/
|-- docs/
|   `-- GITHUB.md
`-- data/
```

Thu muc `data/`, `logs/`, virtualenv va file secret local duoc bo qua khi commit.

## Vai tro module

`main.py`

- Dieu phoi pipeline crawl v2.0.
- Chi goi `crawl_vnexpress`, `crawl_baochinhphu`, `crawl_ptit`.
- Chong trung URL qua storage, in canh bao neu mot nguon crawl duoc 0 bai.
- Khong ghi de output bang file rong neu tat ca nguon crawl that bai.

`crawlers/base.py`

- Quan ly request, header, timeout, delay.
- Tao BeautifulSoup.
- Chuan hoa text, URL va lazy image.

`crawlers/vnexpress.py`

- Crawl 2 chuyen muc VNExpress: Khoa hoc - Cong nghe va Giao duc.
- Dung selector linh hoat cho `article.item-news`, `.item-news`, `h2/h3.title-news a`, description va lazy image.

`crawlers/baochinhphu.py`

- Crawl chuyen muc Khoa giao / Khoa hoc cong nghe cua Bao Chinh phu.
- Parse linh hoat theo block tin, heading link va URL relative/absolute.

`crawlers/ptit.py`

- Crawl trang Tin tuc chung PTIT.
- Ho tro markup WordPress/Elementor voi `article`, `.post`, `.elementor-post`, `.entry-title`, `h2/h3 a`.

`services/storage.py`

- Luu JSON raw, CSV exports, daily snapshot.
- Cap nhat `data/master/master_articles.csv` de chong trung bai moi.
- Tach processed theo `source`, `newspaper_type`, `content_topic`, `category`.

`services/classifier.py`

- Giu mapping co dinh cho topic/category v2.0.
- Van giu keyword rule cho cac workflow cu neu can.

`services/image_generator.py`

- Ham chinh tao an pham: `generate_news_card(article, output_dir="data/generated_images")`.
- Tao anh 1080 x 1350 px ti le 4:5 bang Pillow.
- Thumbnail nam tren cung, resize cover + center crop de khong meo anh.
- Neu thumbnail rong, loi URL, timeout hoac anh hong thi fallback ve anh `PNews.png`.
- Logo goc tren phai mac dinh la `PNews`.
- Text tieng Viet dung font ho tro Unicode neu co; title gioi han 3 dong, summary gioi han 5 dong.
- Output mac dinh nam trong `data/generated_images/` de web admin/client va Telegram doc cung mot vi tri.

`web_app.py`

- Tu migration SQLite tai `data/cms.sqlite3` khi thieu cot moi.
- Tu import bai tu `data/exports/articles.csv` vao hang doi duyet.
- Tu tao/gan lai news card neu `image_path` bi thieu hoac file anh khong con ton tai.
- Admin cho phep click vao anh an pham, tieu de, tom tat va link `Bai goc` de mo dung URL bai bao.
- Client sap xep bai da duyet theo thoi gian moi nhat; neu cung ngay thi uu tien tin PTIT.

## Quy trinh xu ly du lieu v2.0

1. Crawl VNExpress, Bao Chinh phu va PTIT.
2. Bo qua bai thieu `title` hoac `url`.
3. Chuan hoa URL tuyet doi, thumbnail lazy image va metadata co dinh.
4. Xoa trung theo URL.
5. So sanh voi `data/master/master_articles.csv` de lay bai moi.
6. Luu:
   - `data/raw/articles.json`
   - `data/exports/articles.csv`
   - `data/raw/new_articles.json`
   - `data/exports/new_articles.csv`
   - `data/master/master_articles.csv`
   - `data/daily/YYYY-MM-DD/...`
   - `data/processed/...`
7. Cac buoc enrich summary, generate news card, CMS va Telegram tiep tuc dung cung format du lieu.
8. `run_crawler.bat` goi `scripts/sync_cms_from_csv.py` de import CSV moi vao `data/cms.sqlite3`, giup web admin/client nhan bai moi sau lich crawl 7h ma khong can restart server.

## Tao va kiem tra an pham news card

Tao thu 3-5 an pham tu du lieu hien co, khong can API key va khong can crawl moi:

```powershell
python scripts/test_generate_news_cards.py
```

Script uu tien doc `data/exports/articles.csv`, neu khong co thi doc `data/raw/articles.json`, sau do moi tao bai demo. Anh tao ra duoc in duong dan va nam trong `data/generated_images/`.

## Cai dat

Yeu cau Python 3.11+.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Cau hinh API key

Sao chep file mau `.env`:

```powershell
Copy-Item .env.example .env
```

Sau do dien key that vao `.env`. File nay da duoc ignore de khong day len GitHub.

## Cau hinh tai khoan admin

Admin login bat buoc lay tu bien moi truong hoac file `.env` local, khong hardcode trong source code:

```powershell
$env:PNEWS_ADMIN_ACCOUNTS='{"admin":"your_strong_password"}'
```

Co the cau hinh nhieu tai khoan bang JSON object. File `.env` da duoc ignore, chi commit `.env.example` voi gia tri mau.

## Chay crawler

```powershell
python -X utf8 main.py
```

Hoac:

```powershell
python main.py
```

Du lieu dau ra se nam trong `data/`.

## Lich tu dong 7h sang

Windows Task Scheduler dang dung task `Detai1 News Crawler` de chay:

```text
<project>\run_crawler.bat
```

Lich chay: hang ngay luc 07:00. Batch nay thuc hien theo thu tu:

1. Crawl du lieu v2.0 vao `data/raw/` va `data/exports/`.
2. Enrich summary cho `data/exports/new_articles.csv`.
3. Tao news card cho bai moi vao `data/generated_images/YYYY-MM-DD/`.
4. Sync CMS SQLite bang `scripts/sync_cms_from_csv.py` de web admin/client co bai moi.

Kiem tra trang thai task:

```powershell
schtasks /query /tn "\Detai1 News Crawler" /fo LIST /v
```

## Chay web dashboard

```powershell
python web_app.py --host 127.0.0.1 --port 8000
```

Mo:

- Client: `http://127.0.0.1:8000/client`
- Admin: `http://127.0.0.1:8000/admin`
- Dashboard: `http://127.0.0.1:8000/admin/dashboard`

Trang admin:

- `/admin/dashboard`: xem tong quan.
- `/admin`: duyet, tu choi, xoa va go khoi client.
- `/admin/upload`: tai an pham/bai viet thu cong.

Trang client:

- `Tin moi nhat`: tat ca bai da duyet, bai moi len truoc.
- `Tin tuc chung`: cac bai khong thuoc PTIT.
- `Tin tuc PTIT`: chi cac bai nguon PTIT.
- Bo loc ngay mac dinh la ngay hom nay; dung `Tat ca ngay` de xem toan bo bai da duyet.
- O chon ngay co gioi han toi da la ngay hien tai.

## Don dep runtime output

Nhung thu muc/file sau la output runtime va da duoc bo qua trong `.gitignore`:

- `__pycache__/`, `*.pyc`
- `logs/`, `*.log`
- `data/raw/`, `data/exports/`, `data/generated_images/`, `data/thumbnails/`
- `data/cms.sqlite3`, `data/master/`, `data/daily/`, `data/processed/`

Khong xoa `data/generated_images/` khi web admin/client dang can hien thi an pham da duyet. Chi nen xoa cac anh test khong duoc SQLite tham chieu, cac log rong va cache Python.

## Kiem tra nhanh

```powershell
python -m py_compile main.py web_app.py crawlers\base.py crawlers\vnexpress.py crawlers\baochinhphu.py crawlers\ptit.py services\classifier.py services\storage.py services\image_generator.py services\notification_service.py
python -X utf8 main.py
python scripts\test_generate_news_cards.py
```

## Dua len GitHub

Xem huong dan chi tiet tai `docs/GITHUB.md`.
