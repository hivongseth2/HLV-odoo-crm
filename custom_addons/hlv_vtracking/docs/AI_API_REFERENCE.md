# V-Tracking AI API — Tra cứu endpoint

Base URL `/api/v1/ai` · header `X-API-Key` · khung phản hồi và quy ước dữ liệu: xem
[AI_API_GUIDE.md](AI_API_GUIDE.md). Ký hiệu 🔒 = cần khoá bật **"Cho phép ghi"**.

| # | Method | Đường dẫn | Việc |
|---|---|---|---|
| 1 | GET | `/context` | Kho, xe, buổi, định mức, luật nghiệp vụ |
| 2 | GET | `/fleet` | Tình hình xe + kế hoạch trong ngày + buổi trống |
| 3 | GET | `/orders/pending` | Đơn bán còn phải giao |
| 4 | GET | `/orders/<id>` · `/orders/by-name?name=` | Chi tiết một đơn |
| 5 | GET | `/orders/<id>/chatter` | Hội thoại của đơn |
| 6 | GET | `/pickings/ready` | Phiếu xuất xếp lên xe được ngay |
| 7 | GET | `/pickings/<id>` | Chi tiết một phiếu kho |
| 8 | GET | `/plans` | Danh sách kế hoạch theo ngày |
| 9 | GET | `/plans/<id>` | Chi tiết kế hoạch: từng chặng, giờ tới từng điểm |
| 10 | POST | `/estimate` | Thử một lộ trình giả định — không ghi |
| 11 | POST 🔒 | `/plans` | Tạo kế hoạch |
| 12 | POST 🔒 | `/plans/<id>/documents` | Xếp phiếu / đơn vào kế hoạch |
| 13 | POST 🔒 | `/plans/<id>/remove-lines` | Gỡ dòng khỏi kế hoạch |
| 14 | POST 🔒 | `/plans/<id>/resequence` | Đặt lại thứ tự ghé |
| 15 | POST 🔒 | `/plans/<id>/state` | Chốt / về nháp / huỷ / xong |
| 16 | POST 🔒 | `/geocode` | Tra toạ độ một địa chỉ (có thể tốn tiền) |

---

## 1. `GET /context`

Không tham số. Gọi một lần đầu phiên.

```json
{
  "today": "2026-09-18", "timezone": "Asia/Ho_Chi_Minh",
  "sessions": [{"code": "morning", "label": "Sáng"}, {"code": "afternoon", ...}, {"code": "full_day", ...}],
  "route_params": {"speed_kmh": 35.0, "minutes_per_stop": 10, "road_factor": 1.3},
  "fulfillment_stages": [{"code": "ready_to_ship", "label": "...", "can_load": true}, ...],
  "warehouses": [{"id": 1, "name": "Kho Bến Cam", "code": "KBC", "delivery_steps": "pick_pack_ship",
                  "start_place_id": 3, "coords": {"latitude": 10.70, "longitude": 106.92}}],
  "vehicles": [{"id": 5, "license_plate": "60K-12177", "model": "...", "driver": null}],
  "business_rules": ["...", "..."]
}
```

`warehouses[].start_place_id` là giá trị truyền vào `start_place_id` khi tạo kế hoạch xuất
phát từ kho đó. `null` = kho chưa được gắn địa điểm trên bản đồ (không tính được chặng đầu).

## 2. `GET /fleet`

| Tham số | | |
|---|---|---|
| `date` | `YYYY-MM-DD` | Ngày xem kế hoạch. Mặc định hôm nay. Vị trí xe luôn là hiện tại |

Mỗi phần tử `vehicles[]`:

| Khoá | Nghĩa |
|---|---|
| `id`, `name` | id xe trong Odoo, biển số |
| `latitude`, `longitude`, `geocoding` | Vị trí đồng bộ gần nhất + mô tả bằng chữ |
| `status` | `run` / `stop` / `park` / `offline` / `badgps` |
| `position_at`, `is_stale` | Tin GPS gần nhất lúc nào; `true` = quá 30 phút không có tin |
| `alarm_text` | Cảnh báo đang bật (lái quá giờ, SOS…), rỗng nếu không có |
| `plans[]` | Kế hoạch của ngày `date` — tóm tắt, không kèm từng điểm |
| `day_load` | Cộng dồn cả ngày: `plan_count`, `stop_count`, `amount_total`, `distance_km`, `total_minutes` |
| `free_sessions` | Buổi còn xếp được: tập con của `morning`, `afternoon`, `full_day` |

## 3. `GET /orders/pending`

Đơn đã xác nhận, chưa giao đủ. Sắp theo ngày hẹn giao sớm nhất.

| Tham số | Nghĩa |
|---|---|
| `warehouse_id` | Chỉ đơn của kho này |
| `search` | Khớp số đơn hoặc tên khách |
| `commitment_from`, `commitment_to` | Lọc theo ngày hẹn giao |
| `stage` | Lọc theo giai đoạn kho (mã ở `/context`). **Áp trên trang đang lấy** |
| `unplanned_only=1` | Bỏ đơn đã nằm trong kế hoạch. **Áp trên trang đang lấy** |
| `limit` (50, tối đa 200), `offset` | Phân trang. `total` là tổng trước khi lọc `stage`/`unplanned_only` |

Mỗi phần tử `orders[]`:

```json
{
  "id": 812, "name": "DH125524949235898",
  "customer": {"id": 77, "name": "CÔNG TY TNHH ...", "contact_name": "...", "phone": "..."},
  "order_date": "...Z", "commitment_date": "...Z", "amount_total": 3259440.0,
  "delivery_status": "pending",
  "warehouse_id": 1, "warehouse": "Kho Bến Cam",
  "delivery": {
    "address": "Đường số 9, KCN Long Thành, ...", "address_source": "picking",
    "coords": {"latitude": 10.78, "longitude": 106.95, "geo_state": "confirmed"},
    "contact": {...}, "method_note": "GỬI CPN"
  },
  "fulfillment": {"stage": "packing", "stage_label": "Đang đóng gói", "can_load": false,
                  "ready_out_picking_ids": []},
  "supply": {"supply_state": "waiting", "purchase_count": 2,
             "waiting_purchases": ["DMH22289"],
             "expected_arrival": "2026-09-10T03:00:00Z", "expected_arrival_date": "2026-09-10"},
  "plan": null,
  "latest_note": {"date": "...Z", "author": "Nhân viên Đà Nẵng", "body": "Khách nghỉ lễ đến 3/9, ngày 4/9 giao"}
}
```

- `delivery.coords = null` → địa chỉ **chưa từng được tra**. Toạ độ sẽ được tra khi xếp vào kế hoạch.
- `delivery.address_source`: `picking` = lấy từ phiếu xuất (đáng tin hơn), `order` = từ đơn.
- `supply.supply_state`: `no_purchase` (lấy từ tồn kho) · `waiting` (**hàng chưa về đủ**) · `arrived`.
- `plan`: `null` hoặc danh sách `{plan_id, plan_name, plan_state, line_id, reference}`.

## 4. `GET /orders/<id>` · `GET /orders/by-name?name=<số đơn>`

Mọi khoá của mục 3, thêm:

| Khoá | Nghĩa |
|---|---|
| `fulfillment.steps[]` | Từng phiếu kho: `picking_id`, `name`, `step` (pick/pack/out), `state`, `scheduled_date`, `date_done`, `is_backorder`, `plan_id` |
| `supply.purchases[]` | Từng đơn mua: `name`, `vendor`, `state`, `receipt_status` (`not_confirmed`/`pending`/`partial`/`full`), `expected_arrival`, `warehouse`, `qty_ordered`, `qty_received`, `lines[]` |
| `load` | `line_count`, `total_qty`, `total_weight_kg`, `total_volume_m3`, `weight_coverage` (0–1), `package_count` |
| `lines[]` | `product`, `uom`, `qty_ordered`, `qty_delivered`, `qty_remaining`, `price_subtotal`, `weight_kg` |
| `salesperson`, `note` | Người bán; ghi chú trên đơn (văn bản thuần) |
| `chatter[]` | 15 tin do người viết gần nhất (cấu trúc như mục 5) |

## 5. `GET /orders/<id>/chatter`

| Tham số | Nghĩa |
|---|---|
| `limit` | Mặc định 30, tối đa 100. Mới nhất trước |
| `include_system=1` | Lấy cả tin hệ thống, kèm `changes[]` = `{field, old, new}` |

`messages[]`: `id`, `date`, `author`, `type` (`comment`/`email`/…), `is_internal_note`,
`subject`, `body` (văn bản thuần, cắt ở 1200 ký tự), `attachment_count`.

`is_internal_note: true` = ghi chú nội bộ, khách không thấy.

## 6. `GET /pickings/ready`

Phiếu **xuất**, trạng thái Sẵn sàng, chưa xếp xe, đơn bán chưa đóng — đúng tập phiếu người
điều phối thấy trong hộp thoại "Xếp lên xe". Tham số: `warehouse_id`, `search`,
`limit` (100, tối đa 300), `offset`.

`pickings[]`: `id`, `name`, `step`, `state`, `sale_order_id`, `sale_order`, `customer`,
`warehouse_id`, `warehouse`, `scheduled_date`, `amount`, `address`, `coords`, `plan_id`,
`is_backorder`.

## 7. `GET /pickings/<id>`

Mọi khoá của mục 6, thêm `moves[]` (`product`, `uom`, `qty_demand`, `qty_done`,
`weight_kg`), `package_count`, `packages[]`, `note`, `chatter[]`.

## 8. `GET /plans`

Tham số: `date` **hoặc** `date_from` + `date_to` (tối đa 31 ngày); `vehicle_id`;
`include_cancelled=1`. Trả `plans[]` dạng tóm tắt:

`id`, `name`, `date`, `session`, `state` (`draft`/`confirmed`/`done`/`cancelled`),
`vehicle_id`, `vehicle_plate`, `line_count`, `amount_total`, `distance_km`, `drive_minutes`,
`service_minutes`, `total_minutes`, `duration_display`, `missing_coords_count`, `start`,
và khối thực tế `has_actual_data`, `actual_line_count`, `actual_amount_total`,
`actual_distance_km` (**hiện luôn rỗng** — chờ nối với module shipper).

## 9. `GET /plans/<id>`

Tóm tắt như mục 8, thêm `note`, `route_params`, và `lines[]` theo thứ tự ghé:

| Khoá | Nghĩa |
|---|---|
| `id` | **id dòng** — dùng cho `remove-lines` và `resequence` |
| `seq_no` | Số thứ tự ghé, khớp với tờ kế hoạch in ra |
| `reference`, `picking_id`, `sale_order_id`, `source_name` | Chứng từ |
| `partner_name`, `address`, `amount` | Khách, địa chỉ, tiền |
| `latitude`, `longitude`, `has_coords` | Toạ độ điểm giao |
| `waiting_picking` | `true` = xếp theo đơn, phiếu xuất chưa có |
| `leg_km`, `leg_minutes` | Chặng từ điểm trước tới điểm này. `null` = điểm này thiếu toạ độ |
| `arrive_offset_minutes`, `depart_offset_minutes` | Phút tính **từ lúc xe xuất phát** |
| `delivered` | Đã giao chưa (hiện luôn `false` — chờ module shipper) |

Giờ tới thật = giờ xuất phát bạn giả định + `arrive_offset_minutes`. Hệ thống không lưu giờ
xuất phát; buổi sáng/chiều bắt đầu mấy giờ là điều phải hỏi người dùng.

## 10. `POST /estimate` — không ghi gì

```json
{"start_place_id": 3,
 "stops": [{"picking_id": 1201}, {"sale_order_id": 812},
           {"latitude": 10.78, "longitude": 106.95, "label": "điểm thử"},
           {"address": "12 Lê Lợi, Q.1, TP.HCM"}]}
```

Tối đa 60 điểm. Trả `distance_km`, `drive_minutes`, `service_minutes`, `total_minutes`,
`duration_display`, `missing_coords_count`, `route_params`, và `stops[]` kèm `has_coords`,
`leg_km`, `leg_minutes`, `arrive_offset_minutes`, `depart_offset_minutes`.

**Chỉ dùng toạ độ đã có sẵn**, không gọi geocoder. Điểm chưa có toạ độ vẫn được tính thời
gian giao và đánh dấu `has_coords: false`.

## 11. `POST /plans` 🔒

```json
{"vehicle_id": 5, "date": "2026-09-19", "session": "morning", "start_place_id": 3}
```

Trả chi tiết kế hoạch + `created`. Đã có kế hoạch cho (xe, ngày, buổi) thì trả lại cái có
sẵn với `created: false` — **không phải lỗi**. Lỗi 422 khi xe chưa bật theo dõi, hoặc điểm
xuất phát chưa có toạ độ / chưa gắn kho.

## 12. `POST /plans/<id>/documents` 🔒

```json
{"picking_ids": [1201, 1203], "sale_order_ids": [812]}
```

Tối đa 100 chứng từ một lần. Trả:

```json
{"added_line_ids": [55, 56],
 "rejected": [{"id": 812, "name": "DH...", "reason": "already_planned", "detail": "Đã nằm trong kế hoạch ..."}],
 "not_found": {"picking_ids": [], "sale_order_ids": []},
 "plan": { ...chi tiết như mục 9... }}
```

Xếp vào kế hoạch sẽ **tra toạ độ** địa chỉ chưa có trong kho toạ độ (có thể tốn lượt Google).

## 13. `POST /plans/<id>/remove-lines` 🔒

`{"line_ids": [55]}` — **id dòng**, không phải id phiếu. Trả `removed_line_ids` + `plan`.
Id không thuộc kế hoạch này bị bỏ qua: đối chiếu `removed_line_ids` với thứ bạn gửi.

## 14. `POST /plans/<id>/resequence` 🔒

`{"line_ids": [56, 55, 57]}` — thứ tự mong muốn. Dòng không nêu giữ thứ tự tương đối và dồn
xuống cuối. Hoặc `{"strategy": "nearest"}` — hệ thống sắp theo "tới điểm gần nhất chưa ghé"
(điểm khởi đầu tốt, không phải tối ưu). Trả chi tiết kế hoạch sau khi sắp.

## 15. `POST /plans/<id>/state` 🔒

`{"action": "confirm"}` — một trong `confirm`, `back_to_draft`, `cancel`, `done`.
Kế hoạch `done` / `cancelled` không sửa được nữa (422).

## 16. `POST /geocode` 🔒

`{"address": "..."}` → `address_id`, `normalized_address`, `geo_state`, `latitude`,
`longitude`, `from_cache`. Tìm trong kho toạ độ trước; không có mới gọi geocoder ngoài —
**lượt gọi mới tốn tiền**, nên chỉ dùng khi thật sự cần toạ độ của một địa chỉ chưa từng
xuất hiện. Toạ độ rơi ngoài Việt Nam bị từ chối: `latitude`/`longitude` là `null`,
`geo_state = "failed"`.

---

## Ví dụ một phiên làm việc

```bash
H='X-API-Key: <khoá>'; B='https://odoo.example.com/api/v1/ai'
curl -s -H "$H" "$B/context"
curl -s -H "$H" "$B/fleet?date=2026-09-19"
curl -s -H "$H" "$B/pickings/ready?warehouse_id=1"
curl -s -H "$H" "$B/orders/pending?warehouse_id=1&unplanned_only=1"
curl -s -H "$H" -H 'Content-Type: application/json' -X POST "$B/estimate" \
     -d '{"start_place_id":3,"stops":[{"picking_id":1201},{"picking_id":1203}]}'
curl -s -H "$H" -H 'Content-Type: application/json' -X POST "$B/plans" \
     -d '{"vehicle_id":5,"date":"2026-09-19","session":"morning","start_place_id":3}'
curl -s -H "$H" -H 'Content-Type: application/json' -X POST "$B/plans/41/documents" \
     -d '{"picking_ids":[1201,1203]}'
curl -s -H "$H" -H 'Content-Type: application/json' -X POST "$B/plans/41/resequence" \
     -d '{"strategy":"nearest"}'
```
