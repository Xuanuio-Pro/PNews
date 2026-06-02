# IEC News CMS Web App v2.1

Web app bo sung lop admin/client cho project crawler tin tuc.

## Chay server

```powershell
python web_app.py --host 127.0.0.1 --port 8000
```

Mo trinh duyet:

- Client: `http://127.0.0.1:8000/client`
- Admin: `http://127.0.0.1:8000/admin`
- Admin dashboard: `http://127.0.0.1:8000/admin/dashboard`
- Upload an pham: `http://127.0.0.1:8000/admin/upload`

Tai khoan mac dinh:

- User: `admin`
- Password: `admin123`

Nen doi bang bien moi truong khi chay that:

```powershell
$env:IEC_ADMIN_USER="admin"
$env:IEC_ADMIN_PASSWORD="mat-khau-moi"
python web_app.py --host 127.0.0.1 --port 8000
```

## Luong su dung

1. Khi server chay lan dau, app tao SQLite DB tai `data/cms.sqlite3`.
2. App import bai viet tu `data/exports/articles.csv` vao hang doi cho duyet.
3. Admin vao `/admin` de duyet, tu choi, xoa hoac khoi phuc bai viet.
4. Client tai `/client` chi hien thi cac bai da duyet/dang.
5. Admin co the upload an pham moi tai `/admin/upload`.
6. Dashboard tai `/admin/dashboard` hien thi tong quan nguon bao, chu de, bai moi va canh bao chat luong.

## Dieu huong va trai nghiem admin

- Moi trang admin hien thi 3 nut dieu huong nhanh toi cac trang con lai: tong quan, duyet bai, tai an pham va client.
- Trang duyet bai cho phep chon nhieu bai va hien thong bao cho khi dang xu ly duyet/xoa/go khoi client.
- Trang duyet bai mac dinh loc theo ngay hom nay, chan ngay tuong lai va co nut `Tat ca ngay` de xem toan bo.
- Bai da duyet co nut `Export PNG`; nut export hang loat bi khoa cho den khi tick it nhat mot bai.
- Nut `Mo bai` rieng da duoc bo; admin click vao anh an pham, tieu de, tom tat hoac link `Bai goc` de mo dung URL bai bao.
- Phan ngay dang, crawl, cap nhat va ngay duyet chi dung de xem thong tin, khong bat click mo bai.

## Client

- Client co 3 nut loc nhanh: `Tin moi nhat`, `Tin tuc chung`, `Tin tuc PTIT`.
- `Tin moi nhat` sap xep theo thoi gian moi nhat truoc.
- `Tin tuc chung` loc cac bai khong thuoc PTIT.
- `Tin tuc PTIT` loc rieng cac bai nguon PTIT.
- Client co bo loc ngay giong admin: mac dinh hom nay, khong chon ngay tuong lai, co nut `Tat ca ngay`.
- Form loc admin/client tu dong submit khi doi tu khoa, nguon, chu de hoac ngay nen khong can nut `Tim`.
- Neu cac bai cung ngay, bai PTIT duoc uu tien trong nhom ngay do; bai moi hon van duoc dua len truoc.

## Du lieu va media

- Database: `data/cms.sqlite3`
- Anh upload tu admin: `data/uploads/`
- Anh news card sinh tu dong: `data/generated_images/`
- Static CSS/JS: `web_assets/`

News card duoc tao boi `services/image_generator.py` qua ham `generate_news_card(article, output_dir="data/generated_images")`. Anh su dung canvas 1080 x 1350 px, thumbnail cover/crop o phan tren, logo `P-News`, tieu de toi da 3 dong, tom tat toi da 5 dong va nguon o goc duoi phai.

Neu bai thieu `image_path` hoac file anh da bi xoa, web app se thu tao lai news card khi render danh sach admin/client. Khong doi thu muc output neu web dang tro toi `data/generated_images/`.

## Sync tu lich crawl 7h

Task Scheduler chay `run_crawler.bat` luc 07:00 moi ngay. Sau cac buoc crawl, enrich summary va tao news card, batch goi:

```powershell
python scripts/sync_cms_from_csv.py
```

Script nay import `data/exports/articles.csv` vao `data/cms.sqlite3` de web admin/client nhan bai moi ma khong phai restart server. Neu can sync thu cong sau khi crawl:

```powershell
python scripts/sync_cms_from_csv.py
```

## Kiem tra nhanh

```powershell
python -m py_compile main.py web_app.py services/image_generator.py services/storage.py services/notification_service.py
python scripts/test_generate_news_cards.py
```

Neu dung virtualenv `detai1`:

```powershell
.\detai1\Scripts\python.exe -m py_compile main.py web_app.py services\image_generator.py services\storage.py services\notification_service.py
.\detai1\Scripts\python.exe scripts\test_generate_news_cards.py
```

## API public

```text
GET /api/articles
GET /api/articles?q=tu-khoa
GET /api/articles?source=VNExpress
GET /api/articles?topic=Cong%20nghe
POST /api/chat
GET /api/chat/suggestions
```

## IEC News Assistant

Trang `/client` co widget chat noi. Chatbot uu tien tra loi dua tren database/rule cho cac cau hoi ve tin moi, chu de, nguon bao va tu khoa. Voi cau hoi can tom tat hoac goi y tu nhien, app co the dung Gemini/Groq neu da cau hinh API key.

Bien moi truong AI tuy chon:

```powershell
$env:GEMINI_API_KEY="your-gemini-key"
$env:GROQ_API_KEY="your-groq-key"
$env:GEMINI_MODEL="gemini-3.1-flash-lite"
$env:GROQ_MODEL="llama-3.1-8b-instant"
```

## Ghi chu v2.1

- Khi doi logo news card, chay lai generator cho cac bai dang co `image_path` de anh export PNG dong bo voi brand moi.
- Runtime SQLite sinh them `data/cms.sqlite3-wal` va `data/cms.sqlite3-shm`; cac file nay duoc ignore va khong nen commit.

## Huong phat trien tiep theo

- Tach ro module auth/admin, API va crawler scheduler.
- Them hang doi xu ly bai moi va thong bao theo chu de.
- Them workflow duyet bai, sinh anh, dang bai va gui thong bao tu dong.
- Bo sung test cho crawler, storage va API dashboard.
