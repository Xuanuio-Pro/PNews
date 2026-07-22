# Admin Content Management

Tai lieu nay mo ta cac luong quan tri noi dung moi trong PNews CMS: phan trang admin, cau hinh thu tu client, chinh sua bai viet va caption Facebook.

## Danh sach admin

- Trang `/admin` hien 12 bai tren moi trang.
- Bo loc ngay mac dinh la ngay hien tai; bam `Tat ca ngay` de xem toan bo bai.
- Cac thao tac hang loat van chi ap dung cho cac bai da tick tren trang hien tai.

## Trang cau hinh client

Admin co trang rieng:

```text
GET /admin/client-config
```

Trang nay dung de quan ly cac bai da duyet dang hien thi tren client:

- Xem toan bo bai `approved` mac dinh, khong bi gioi han theo ngay hom nay.
- Tim kiem theo tieu de, tom tat, nguon.
- Loc theo nguon, chu de va ngay.
- Xem thu tu hien tai cua tung bai tren client.
- Sap xep `Len`/`Xuong`.
- Mo form `Chinh sua`.
- Mo nhanh trang client hoac bai goc.

## Cau hinh bai da duyet tren client

Voi bai co trang thai `approved`, admin co them cac nut:

- `Chinh sua`: mo form sua noi dung hien thi tren client va caption Facebook ke tiep.
- `Len`: dua bai len cao hon trong thu tu client.
- `Xuong`: dua bai xuong thap hon trong thu tu client.

Trong trang `/admin/client-config`, sau khi bam `Len`/`Xuong`, app se quay lai dung bo loc va trang dang xem.

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

Voi bai nhieu anh, caption bai chinh chi gom ten ban tin, thoi gian cap nhat,
mot doan gioi thieu ngan va huong dan bam vao tung anh. Moi anh co caption rieng
gom so thu tu, tieu de, summary toi da 400 ky tu, nguon va URL.

Tai danh sach bai da duyet:

1. Chon it nhat hai bai.
2. Bam `Xem truoc Facebook`.
3. Kiem tra thu tu anh va caption; bo chon neu muon loai anh khoi batch.
4. Sua caption truc tiep hoac bam `Sua noi dung bai goc`.
5. Chay `Dang thu (dry-run)` truoc khi dang that.

Dry-run ghi JSON tai `data/facebook_previews/` va khong goi Graph API.

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
