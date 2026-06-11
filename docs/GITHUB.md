# Huong dan dua du an len GitHub

Tai lieu nay dung de luu tru va day phien ban v2.1 cua du an len GitHub.

## 1. Kiem tra truoc khi commit

Chay cac lenh sau trong thu muc du an:

```powershell
git status --short
git diff
python -m py_compile main.py web_app.py services/facebook_service.py services/image_generator.py services/storage.py services/notification_service.py
python -m py_compile scripts/sync_cms_from_csv.py scripts/test_facebook_publish.py
python scripts/test_generate_news_cards.py
```

Dam bao khong commit cac file sau:

- `.env`
- Tai khoan admin, token Facebook, API key Gemini/Groq/Telegram that
- `detai1/`, `.venv/`, `venv/`
- `logs/`
- `data/` sinh ra khi crawl, database, cache anh
- `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`

File cau hinh mau an toan nam tai `.env.example`.

## Don dep truoc khi commit

Chi nen commit source code, docs va file cau hinh mau. Cac output runtime sau co the xoa neu khong can backup:

- Cache Python: `__pycache__/`, `*.pyc`
- Log rong hoac log chay thu trong `logs/`
- Anh test khong duoc SQLite tham chieu trong `data/generated_images/`

Khong xoa toan bo `data/generated_images/` neu dang can kiem tra admin/client, vi SQLite co the dang tro toi cac file anh trong do.

## 2. Commit phien ban v2.1

```powershell
git add .
git commit -m "release: v2.1"
git branch -M main
```

Gan tag cho moc v2.1:

```powershell
git tag v2.1
```

## 3. Tao repository tren GitHub

Vao GitHub va tao repository moi, vi du:

- Repository name: `iec-news-crawler`
- Visibility: `Private` neu du an co du lieu noi bo, `Public` neu muon chia se
- Khong tick tao san README, `.gitignore`, hoac license neu repo local da co san

## 4. Ket noi remote va push

Thay `YOUR_USERNAME` va `iec-news-crawler` bang tai khoan/repository cua ban:

```powershell
git remote add origin https://github.com/YOUR_USERNAME/iec-news-crawler.git
git push -u origin main
git push origin v2.1
```

Neu dung SSH:

```powershell
git remote add origin git@github.com:YOUR_USERNAME/iec-news-crawler.git
git push -u origin main
git push origin v2.1
```

## 5. Tao nhanh nhanh phat trien sau v2.1

Sau khi push xong, tao branch rieng neu muon nang cap tiep:

```powershell
git switch -c v2.2-dev
git push -u origin v2.2-dev
```

Lam viec tren branch phat trien, con `main` giu vai tro moc on dinh.
