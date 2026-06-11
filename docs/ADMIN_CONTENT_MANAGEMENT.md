# Admin Content Management

Tai lieu nay mo ta cac luong quan tri noi dung moi trong PNews CMS: phan trang admin, cau hinh thu tu client, chinh sua bai viet va caption Facebook.

## Danh sach admin

- Trang `/admin` hien 12 bai tren moi trang.
- Bo loc ngay mac dinh la ngay hien tai; bam `Tat ca ngay` de xem toan bo bai.
- Cac thao tac hang loat van chi ap dung cho cac bai da tick tren trang hien tai.

## Cau hinh bai da duyet tren client

Voi bai co trang thai `approved`, admin co them cac nut:

- `Chinh sua`: mo form sua noi dung hien thi tren client va caption Facebook ke tiep.
- `Len`: dua bai len cao hon trong thu tu client.
- `Xuong`: dua bai xuong thap hon trong thu tu client.

He thong luu thu tu bang cot `client_order` trong SQLite:

- `client_order > 0`: bai duoc sap theo thu tu thu cong, so nho hon dung truoc.
- `client_order = 0`: bai dung thu tu mac dinh theo ngay duyet/cap nhat, uu tien PTIT trong cung nhom ngay.
- Khi bam `Len`/`Xuong`, app chuan hoa lai `client_order` cho tat ca bai da duyet de thu tu client on dinh.

## Chinh sua bai viet

Route:

```text
GET  /admin/articles/{article_id}/edit
POST /admin/articles/{article_id}/edit
```

Form cho phep sua:

- Tieu de
- Tom tat
- Nguon
- Chu de
- Chuyen muc
- Link bai goc
- Ngay dang
- Thu tu client
- Anh moi

Khi bai chua dang Facebook thanh cong, viec sua noi dung se xoa caption Facebook da luu de preview va lan dang tiep theo dung noi dung moi. Bai da dang Facebook thanh cong van giu caption lich su cua post da dang.

## Chuan caption Facebook

Caption moi chi co mot moc thoi gian cho ca bai dang:

```text
TIN TUC MOI TU PNEWS
Cap nhat ngay dd/mm/YYYY HH:MM

1. Tieu de bai viet
Tom tat bai viet
Nguon: Ten nguon
Xem chi tiet: https://...

#PNews #PTIT #TinTucCongNghe #GiaoDuc #KhoaHocCongNghe
```

Quy tac:

- Khong hien `Ngay/gio bai bao` rieng cho tung bai.
- Khong them cau footer `PNews tu dong tong hop...`.
- Dang nhieu bai se tao mot post multi-photo duy nhat voi danh sach bai trong caption.
- Dang mot bai van dung cung header `TIN TUC MOI TU PNEWS` va dong `Cap nhat ngay ...`.

## Kiem tra sau khi thay doi

```powershell
python -m py_compile web_app.py services\facebook_service.py scripts\test_facebook_publish.py
python scripts\test_generate_news_cards.py
```

Neu can kiem tra UI:

```powershell
python web_app.py --host 127.0.0.1 --port 8000
```

Mo:

- `http://127.0.0.1:8000/client?date=all`
- `http://127.0.0.1:8000/admin`

Luu y: `scripts/test_facebook_publish.py` se dang bai test len Facebook Page that neu da cau hinh token, chi chay khi muon test Graph API.
