# Luong xac thuc Admin/Client PNews

Tai lieu nay mo ta hanh vi dang nhap va session giua khu vuc admin va client cua PNews CMS.

## Muc tieu

- Client la khu vuc public, khong can dang nhap.
- Admin la khu vuc quan tri, luon can session hop le.
- Khi admin roi khu vuc quan tri de sang client, session admin phai bi huy.
- Tu client quay lai admin phai hien form dang nhap, khong vao thang dashboard/danh sach duyet.

## Session admin

Session admin duoc luu bang cookie:

```text
pnews_cms_session
```

Cookie nay duoc tao sau khi dang nhap thanh cong o `POST /admin/login`.

Tat ca route admin can session hop le:

```text
/admin
/admin/dashboard
/dashboard
/admin/client-config
/admin/upload
/admin/articles/*
/admin/bulk
```

Neu khong co session hop le, request vao admin se duoc dua ve trang dang nhap `/admin`.

## Hanh vi khi sang client

Khi request HTML public vao cac route sau, app se xoa session admin neu cookie dang ton tai:

```text
/client
/client/article/{id}
```

Dieu nay giup tranh tinh huong:

1. Dang o admin.
2. Bam `Xem client`.
3. Quay lai `/admin`.
4. Vao thang admin/dashboard ma khong can dang nhap lai.

Sau thay doi nay, buoc 4 phai hien trang dang nhap.

Luu y: viec xoa session chi ap dung cho trang HTML client. Static assets va media khong tao/huy session.

## Cache headers

Admin va client HTML lien quan den chuyen session deu gui header:

```text
Cache-Control: no-store, no-cache, must-revalidate, max-age=0
Pragma: no-cache
Expires: 0
```

Muc dich la tranh browser khoi phuc trang admin cu tu back-forward cache.

## Checklist test thu cong

1. Mo `http://127.0.0.1:8000/admin`.
2. Dang nhap admin.
3. Bam `Xem client`.
4. Quay lai `http://127.0.0.1:8000/admin`.
5. Ket qua dung: hien form dang nhap admin.
6. Mo `http://127.0.0.1:8000/admin/dashboard`.
7. Ket qua dung: van hien form dang nhap admin.

Checklist HTTP:

1. Login bang `POST /admin/login`.
2. Goi `GET /client`.
3. Kiem tra response co `Set-Cookie: pnews_cms_session=; Max-Age=0`.
4. Goi lai `GET /admin` voi cookie cu.
5. Ket qua dung: body la trang dang nhap, khong phai dashboard/admin list.
6. Goi `GET /admin/dashboard` hoac `GET /dashboard` voi cookie cu.
7. Ket qua dung: body van la trang dang nhap.

## Ghi chu van hanh

- Chuyen tu admin sang client duoc xem nhu "roi admin", nen can dang nhap lai khi quay ve admin.
- Neu chi muon mo client ma van giu phien admin, can thay doi chinh sach nay trong code truoc khi van hanh.
- Khong dua token Facebook hoac mat khau admin vao docs.
