---
name: du-lieu-dieu-phoi
description: Bảo trì dữ liệu nền của V-Tracking qua API — sửa địa chỉ, nhập/duyệt/tra lại toạ độ, dò và gộp địa chỉ/địa điểm trùng, sửa thói quen khách, sửa định mức cụm tuyến, khai chuyên chở/tài xế/điểm xuất phát của xe. Dùng khi được yêu cầu "update địa chỉ", "tìm geo code", "clear duplicate", "gắn tài xế cho xe", "sửa định mức"... Không dùng để lập kế hoạch giao (đó là skill dieu-phoi-giao-hang).
---

# Dữ liệu nền điều phối

Mọi lời gọi đi qua script của skill điều phối, cùng khoá API, cùng cách cấu hình:

```
python .claude/skills/dieu-phoi-giao-hang/scripts/vt.py get  "places?no_zone=1&limit=100"
python .claude/skills/dieu-phoi-giao-hang/scripts/vt.py post places/12 '{"type_code": "warehouse", "warehouse_id": 1}'
```

Đường dẫn **không có `/` đầu**. Tên endpoint và ô sửa được: đọc mục 20–24 của
`custom_addons/hlv_vtracking/docs/AI_API_REFERENCE.md` — đừng đoán.

## Ranh giới cứng

1. **Gộp trùng luôn hai bước, có người duyệt ở giữa.** Gọi `.../duplicates`, trình bày
   từng nhóm (id, tên/địa chỉ, toạ độ, lý do, bản đề xuất giữ), **chờ người dùng đồng ý**
   rồi mới `.../merge` với đúng `keep_id` + `merge_ids` đã duyệt. Người dùng nói "gộp hết
   đi" thì vẫn liệt kê trước một lần rồi mới gộp — gộp sai là mất lịch sử.
2. **Nhóm địa điểm chỉ có lý do `same_customer`** có thể là hai nhà máy thật của một khách.
   Hỏi riêng từng nhóm, đừng gộp theo lô.
3. **Tra toạ độ tốn tiền.** Báo trước số lượt sẽ gọi khi quá ~10 địa chỉ. Ưu tiên nhập toạ
   độ người dùng đưa (ghim Google Maps) hơn tra lại.
4. **Không đè toạ độ `manual`.** API đã chặn, đừng tìm cách vòng (xoá rồi nhập lại).
5. **Sửa định mức cụm là đổi giờ của mọi kế hoạch nháp dùng cụm đó.** Đọc lại `before` /
   `after` cho người dùng. Áp đề xuất học từ thực tế chỉ khi người dùng bảo.
6. Không đụng kế hoạch, đơn, phiếu kho ở skill này.

## Công việc thường gặp

**"Update địa chỉ / toạ độ của X"**
1. `get "places?search=X"` (và/hoặc `addresses?search=...`) — tìm đúng bản ghi, nhiều kết
   quả thì hỏi.
2. Người dùng đưa toạ độ → `post places/<id> '{"coords": "lat, lng"}'` (thành `manual`).
   Đưa địa chỉ mới → `post places/<id> '{"address": "..."}'` rồi `places/<id>/geocode`.
3. Toạ độ máy tìm được mà người dùng xác nhận đúng → `places/<id>/confirm-geo`.

**"Tìm geo code còn thiếu"**
1. `get "places?has_coords=0&limit=200"` và `get "addresses?geo_state=failed"` /
   `addresses?outside_vietnam=1` — đếm, báo người dùng, hỏi có tra không (tốn tiền).
2. Tra từng cái: `places/<id>/geocode` hoặc `addresses/<id>/geocode`.
3. Kết quả `pending_review` là máy đoán — liệt kê để người duyệt, đừng tự `confirm`.

**"Clear duplicate"**
1. `get addresses/duplicates` và/hoặc `get places/duplicates`.
2. Trình bày dạng bảng, mỗi nhóm một dòng, đánh dấu nhóm `same_customer`-only.
3. Chờ duyệt → `post addresses/merge` / `post places/merge` từng nhóm.
4. Báo số dòng kế hoạch / xe / thói quen đã chuyển (có trong kết quả gộp).
5. Gộp nhầm địa điểm: `post places/<id> '{"active": true}'` mở lại bản đã lưu trữ.

**Kho làm điểm xuất phát**: địa điểm phải `type_code = warehouse` **và** có `warehouse_id`
thì mới hiện trong `context` → `warehouses[].start_place_id`.

**Xe / tài xế**: `get drivers` để lấy `user_id` theo `shipper_name`, rồi
`post vehicles/<id> '{"driver_user_id": ..., "start_place_id": ..., "role": "van", "payload_kg": ...}'`.
Một tài khoản chỉ gắn một xe.

**Thói quen khách**: `post places/<id>/profile` chỉ với các ô người dùng nêu.
`post profiles/seed-known` mồi bảng thói quen đã biết — chạy lại không hại.

## Báo lại

Cuối mỗi lượt: đã sửa gì (id + trước → sau), đã tra toạ độ mấy lượt, còn gì chờ người
duyệt. Lỗi 422 thì đọc thông báo — nó liệt kê giá trị hợp lệ.
