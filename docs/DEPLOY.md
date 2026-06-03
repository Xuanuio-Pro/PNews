# PNews Deploy Guide

Huong dan nay dung cho viec dua PNews len server/host web sau khi code da duoc day len GitHub.

## 1. Chuan bi moi truong

Yeu cau:

- Python 3.11+
- Internet outbound de crawl tin va goi Facebook Graph API neu dung tinh nang dang Facebook
- Thu muc ghi duoc cho `data/` va `logs/`

Tao virtualenv va cai dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 2. Cau hinh bien moi truong

Tao file `.env` tren server tu `.env.example`, sau do dien gia tri that. Khong commit `.env` len GitHub.

Bien bat buoc cho admin:

```text
PNEWS_ADMIN_ACCOUNTS={"admin":"your_strong_password"}
```

Bien tuy chon cho Facebook:

```text
FACEBOOK_PAGE_ID=your_page_id
FACEBOOK_PAGE_ACCESS_TOKEN=your_page_access_token
FACEBOOK_GRAPH_API_VERSION=v25.0
```

Bien tuy chon cho AI/chatbot:

```text
GEMINI_API_KEY=your_gemini_key
GROQ_API_KEY=your_groq_key
```

## 3. Chay ung dung

Chay local/server:

```powershell
python web_app.py --host 0.0.0.0 --port 8000
```

URL:

- Admin: `/admin`
- Dashboard: `/admin/dashboard`
- Client: `/client`

Neu dung reverse proxy, tro proxy ve `127.0.0.1:8000`.

## 4. Du lieu runtime

Nhung du lieu sau sinh ra tren server va khong dua len GitHub:

- `.env`
- `config/api_keys.json`
- `data/cms.sqlite3`
- `data/generated_images/`
- `data/uploads/`
- `logs/`

Khi migrate sang server moi, neu muon giu bai da duyet va anh an pham, copy rieng `data/cms.sqlite3`, `data/generated_images/` va `data/uploads/` bang kenh an toan ngoai GitHub.

## 5. Kiem tra truoc khi publish

```powershell
python -m py_compile main.py web_app.py services\image_generator.py services\facebook_service.py services\storage.py
python scripts\test_generate_news_cards.py
git status --short
```

Quet nhanh secret truoc khi push:

```powershell
rg -n --hidden -S "api_key|secret|token|password|access_token" . -g "!.git/*" -g "!data/*" -g "!*.png" -g "!*.jpg"
```
