# Vietnamese News Crawler

Du an crawl tin tuc tieng Viet tu nhieu nguon bao, chuan hoa du lieu, phan loai noi dung, tao anh news card va phuc vu dashboard web de xem/quan ly bai viet.

## Tinh nang chinh

- Crawl tin tu VNExpress, Dan tri va 24h theo nhieu chuyen muc.
- Chuan hoa du lieu bai viet gom nguon, tieu de, URL, thumbnail, tom tat, chuyen muc va nhom noi dung.
- Luu du lieu ra JSON, CSV, SQLite va cac thu muc phan loai.
- Tao anh news card bang Pillow.
- Ho tro dashboard web Flask, tim kiem bai viet, chatbot/tom tat neu co API key.
- Ho tro gui thong bao Telegram khi cau hinh token va chat ID.

## Cau truc thu muc

```text
Code/
├── main.py
├── web_app.py
├── run_crawler.bat
├── requirements.txt
├── config/
│   └── api_keys.example.json
├── crawlers/
│   ├── base.py
│   ├── vnexpress.py
│   ├── dantri.py
│   └── news24h.py
├── services/
│   ├── storage.py
│   ├── classifier.py
│   ├── image_generator.py
│   ├── notification_service.py
│   └── notifiers/
├── templates/
├── web_assets/
├── docs/
│   └── GITHUB.md
└── data/
```

Thu muc `data/`, `logs/`, virtualenv va file secret local duoc bo qua khi commit.

## Cai dat

Yeu cau Python 3.11+.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Cau hinh API key

Sao chep file mau:

```powershell
Copy-Item config\api_keys.example.json config\api_keys.json
```

Sau do dien key that vao `config/api_keys.json`. File nay da duoc ignore de khong day len GitHub.

Co the cau hinh cac gia tri sau:

- `GEMINI_API_KEY`
- `GROQ_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_DEFAULT_CHAT_ID`
- `ENABLE_TELEGRAM_NOTIFY`

## Chay crawler

```powershell
python main.py
```

Hoac dung file batch:

```powershell
.\run_crawler.bat
```

Du lieu dau ra se nam trong `data/`.

## Chay web dashboard

```powershell
python web_app.py
```

Mo trinh duyet tai dia chi duoc hien thi trong terminal, thuong la `http://127.0.0.1:5000`.

## Kiem tra nhanh truoc khi commit

```powershell
python -m compileall .
git status --short
```

## Dua len GitHub

Xem huong dan chi tiet tai `docs/GITHUB.md`.

Tom tat nhanh:

```powershell
git init
git add .
git commit -m "chore: archive current project before v2"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/iec-news-crawler.git
git push -u origin main
```

Nen tag moc hien tai truoc khi phat trien phien ban 2.0:

```powershell
git tag v1.0.0
git push origin v1.0.0
git switch -c v2.0
```
