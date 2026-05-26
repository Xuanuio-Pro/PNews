# IEC News CMS Web App

Web app bo sung lop admin/client cho project crawler tin tuc.

## Chay server

```powershell
python web_app.py --host 127.0.0.1 --port 8000
```

Mo trinh duyet:

- Client: `http://127.0.0.1:8000/client`
- Admin: `http://127.0.0.1:8000/admin`
- Admin dashboard: `http://127.0.0.1:8000/admin/dashboard`

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

## Du lieu va media

- Database: `data/cms.sqlite3`
- Anh upload tu admin: `data/uploads/`
- Anh news card sinh tu dong: `data/generated_images/`
- Static CSS/JS: `web_assets/`

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

## Huong phat trien v2.0

- Tach ro module auth/admin, API va crawler scheduler.
- Them hang doi xu ly bai moi va thong bao theo chu de.
- Them workflow duyet bai, sinh anh, dang bai va gui thong bao tu dong.
- Bo sung test cho crawler, storage va API dashboard.
