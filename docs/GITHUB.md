# Huong dan dua du an len GitHub

Tai lieu nay dung de luu tru ban hien tai cua du an lam moc truoc khi phat trien phien ban 2.0.

## 1. Kiem tra truoc khi commit

Chay cac lenh sau trong thu muc du an:

```powershell
git status --short
git diff
python -m compileall .
```

Dam bao khong commit cac file sau:

- `config/api_keys.json`
- `.env`
- `detai1/`, `.venv/`, `venv/`
- `logs/`
- `data/` sinh ra khi crawl, database, cache anh

File cau hinh mau an toan nam tai `config/api_keys.example.json`.

## 2. Commit ban luu tru hien tai

```powershell
git add .
git commit -m "chore: archive current project before v2"
git branch -M main
```

Nen gan tag cho moc hien tai:

```powershell
git tag v1.0.0
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
git push origin v1.0.0
```

Neu dung SSH:

```powershell
git remote add origin git@github.com:YOUR_USERNAME/iec-news-crawler.git
git push -u origin main
git push origin v1.0.0
```

## 5. Tao nhanh nhanh phat trien v2.0

Sau khi push xong, tao branch rieng de nang cap:

```powershell
git switch -c v2.0
git push -u origin v2.0
```

Lam viec tren branch `v2.0`, con `main` giu vai tro moc on dinh.
