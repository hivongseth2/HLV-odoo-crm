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
| 16b | POST 🔒 | `/plans/<id>/start` | Đổi điểm xuất phát của kế hoạch đã tạo |
| | | **Dữ liệu nền — xem mục 20–24** | |
| 20 | GET | `/addresses` · `/addresses/<id>` | Kho toạ độ: lọc, xem |
| 20 | POST 🔒 | `/addresses/<id>` · `/addresses/<id>/geocode` | Nhập toạ độ tay / duyệt · tra lại (tốn tiền) |
| 20 | GET · POST 🔒 | `/addresses/duplicates` · `/addresses/merge` | Dò trùng · gộp |
| 21 | GET · POST 🔒 | `/places` | Lọc địa điểm · tạo địa điểm |
| 21 | GET · POST 🔒 | `/places/<id>` | Xem · sửa địa điểm |
| 21 | POST 🔒 | `/places/<id>/geocode` · `/places/<id>/confirm-geo` | Tra lại toạ độ (tốn tiền) · duyệt toạ độ |
| 21 | GET · POST 🔒 | `/places/duplicates` · `/places/merge` | Dò trùng · gộp |
| 22 | POST 🔒 | `/places/<id>/profile` · `/profiles/seed-known` | Sửa thói quen khách · mồi thói quen đã biết |
| 23 | POST 🔒 | `/zones/<id>` · `/zones/<id>/apply-calibration` · `/zones/recalibrate` | Sửa định mức · áp dụng đề xuất · tính lại đề xuất |
| 24 | POST 🔒 · GET | `/vehicles/<id>` · `/drivers` | Sửa chuyên chở + tài xế + điểm xuất phát của xe · danh sách tài xế |
| 25 | GET | `/requests` · `/requests/<id>` | Yêu cầu nhân viên gửi AI |
| 25 | POST 🔒 | `/requests/<id>/claim` · `/answer` · `/fail` | Nhận việc · trả lời · báo bí |

---

## 1. `GET /context`

Không tham số. Gọi một lần đầu phiên.

```json
{
  "today": "2026-09-18", "timezone": "Asia/Ho_Chi_Minh",
  "sessions": [{"code": "morning", "label": "Sáng"}, {"code": "afternoon", ...}, {"code": "full_day", ...}],
  "route_params": {"speed_kmh": 35.0, "minutes_per_stop": 10, "road_factor": 1.3},
  "zone_match_km": 3.0,
  "zones": [{"id": 1, "name": "Nhơn Trạch", "code": "NT", "warehouse_id": 1,
             "hub_to_first_minutes": 40, "median_leg_minutes": 13, "return_minutes": 25,
             "max_stops": 8, "min_stops_worth_trip": 3, "place_count": 48}],
  "fulfillment_stages": [{"code": "ready_to_ship", "label": "...", "can_load": true}, ...],
  "warehouses": [{"id": 1, "name": "Kho Bến Cam", "code": "KBC", "delivery_steps": "pick_pack_ship",
                  "start_place_id": 3, "coords": {"latitude": 10.70, "longitude": 106.92}}],
  "vehicles": [{"id": 5, "license_plate": "60K-12177", "model": "...", "driver": null,
                "capacity": {"role": "van", "role_label": "Xe tải nhỏ / van — chạy tuyến hằng ngày",
                             "payload_kg": 950, "cargo_m": {"length": 2.8, "width": 1.4, "height": 1.4},
                             "max_item_length_m": 4.0, "max_pieces": 15,
                             "note": "Kim Long. Hàng dài quá 4 m thì KHÔNG dùng xe này.",
                             "declared": true}}],
  "business_rules": ["...", "..."]
}
```

`warehouses[].start_place_id` là giá trị truyền vào `start_place_id` khi tạo kế hoạch xuất
phát từ kho đó. **Luôn truyền nó** — bỏ trống thì kế hoạch vẫn tạo được nhưng không tính
chặng kho → điểm đầu và chặng về, thời gian trên kế hoạch thấp hơn thực tế cả tiếng.
`null` = địa điểm loại Kho chưa được gắn ô *Kho trong Odoo* (V-Tracking → Địa điểm → Địa điểm) — nêu
lại cho người dùng.

**`vehicles[].capacity` — đọc trước khi chọn xe.** Ô chưa khai là `null`, không phải 0
(0 kg nghĩa là "không chở được gì", `null` nghĩa là "chưa ai khai"). `note` là lời dặn của
người điều phối viết cho người mới — đọc nguyên văn. `declared: false` = xe chưa khai gì cả:
đừng tự đoán xe đó là loại gì, **hỏi người dùng**. `role: "truck"` chỉ dùng khi hàng quá
khổ; `role: "technical"` là xe đi lắp đặt, không chạy tuyến giao thường.

**`zones[]` là nguồn định mức duy nhất được tin.** Mỗi cụm có thời gian riêng, đo từ chuyến
thật: Nhơn Trạch ra khỏi kho mất 40 phút còn Long Thành 57 phút — dùng một con số chung cho
cả hai là sai cả hai. Các số này được cập nhật sau mỗi lần đối chiếu kế hoạch với thực tế,
nên **đừng dùng số ghi cứng trong skill hay prompt**.

`route_params` chung của công ty chỉ là **giá trị lùi** cho điểm chưa gán cụm.

**Cụm của một điểm giao suy từ TOẠ ĐỘ**, không suy từ khách hàng: hệ thống tìm điểm giao đã
biết gần nhất rồi lấy cụm của điểm đó. Nhờ vậy một khách giao ở hai nơi thuộc hai cụm khác
nhau (nhà máy và kho) vẫn ra đúng hai cụm. `zone_match_km` là bán kính còn tin được — xa
hơn thì vẫn đoán nhưng đánh dấu `zone_uncertain`.

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
| `capacity` | Xe chở được gì — giống khối `capacity` ở `/context` |
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
  "dispatch": {
    "blocking": [{"code": "customs", "label": "Phải khai hải quan trước khi xe vào", "hard": true}],
    "blocked": true,
    "delivery_channel": "company",
    "needs_truck": true,
    "zone": {"id": 2, "name": "Long Thành", "source": "coords",
             "distance_km": 0.8, "uncertain": false},
    "place_id": 41,
    "driver_note": "Cổng số 2, gọi bảo vệ trước 15 phút"
  },
  "revisit_risk": {"within_days": 2,
                   "other_orders": [{"order_id": 903, "order_name": "DH1255...",
                                     "expected_arrival_date": "2026-09-19"}]},
  "latest_note": {"date": "...Z", "author": "Nhân viên Đà Nẵng", "body": "Khách nghỉ lễ đến 3/9, ngày 4/9 giao"}
}
```

- `delivery.coords = null` → địa chỉ **chưa từng được tra**. Toạ độ sẽ được tra khi xếp vào kế hoạch.
- `delivery.address_source`: `picking` = lấy từ phiếu xuất (đáng tin hơn), `order` = từ đơn.
- `supply.supply_state`: `no_purchase` (lấy từ tồn kho) · `waiting` (**hàng chưa về đủ**) · `arrived`.
- `plan`: `null` hoặc danh sách `{plan_id, plan_name, plan_state, line_id, reference}`.

**`dispatch` — phần quan trọng nhất để lọc đơn.**

| Khoá | Nghĩa |
|---|---|
| `blocking[]` | Cờ chặn đã chuẩn hoá: `customs` · `register` (**cứng**) · `pickup` · `express` · `grab` (mềm) |
| `blocked` | Có cờ **cứng**. Xếp vào kế hoạch thì `confirm-plan` sẽ **báo lỗi** |
| `needs_truck` | `false` = khách tự lấy / gửi ngoài, **đừng chiếm một chỗ trên xe** |
| `zone.source` | `coords` (suy từ toạ độ — tin được) · `place` (đoán theo khách) |
| `zone.uncertain` | `true` = máy phải đoán. Định mức thời gian dựa vào cụm, đoán sai cụm là sai cả giờ giấc |
| `driver_note` | Cổng vào, SĐT người nhận, đường khó — chuyển nguyên văn cho tài xế |

`zone` chỉ dùng toạ độ **đã có sẵn** trong kho toạ độ; endpoint này **không bao giờ gọi
geocoder**. Đơn chưa có toạ độ thì `zone.source = "place"` (đoán theo khách) hoặc `null`.

**`revisit_risk`** — khách này còn đơn KHÁC sắp có hàng trong 2 ngày tới. Giao hôm nay thì
vài hôm nữa xe phải chạy lại đúng chỗ đó; chờ một hôm gộp hai đơn là tiết kiệm nguyên một
lượt. Cân nhắc cùng `commitment_date` rồi **nêu lại cho người dùng**, đừng tự hoãn đơn.
`null` = không có rủi ro.

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
`service_minutes`, `return_minutes`, `total_minutes`, `duration_display`,
`missing_coords_count`, `zone_id`, `zone_name`, `zone_warning`, `start`,
và khối thực tế `has_actual_data`, `actual_line_count`, `actual_amount_total`,
`actual_distance_km` — điền từ mốc shipper (nhận hàng, giao xong) bởi cron đối chiếu mỗi giờ; rỗng khi chưa ai quét phiếu.

## 9. `GET /plans/<id>`

Tóm tắt như mục 8, thêm `note`, `route_params`, và `lines[]` theo thứ tự ghé:

| Khoá | Nghĩa |
|---|---|
| `id` | **id dòng** — dùng cho `remove-lines` và `resequence` |
| `seq_no` | Số thứ tự ghé, khớp với tờ kế hoạch in ra |
| `reference`, `picking_id`, `sale_order_id`, `source_name` | Chứng từ |
| `partner_name`, `address`, `amount` | Khách, địa chỉ, tiền |
| `latitude`, `longitude`, `has_coords` | Toạ độ điểm giao |
| `zone_id`, `zone_name` | Cụm tuyến của điểm — quyết định định mức thời gian |
| `zone_source` | `coords` (suy từ toạ độ — tin được) · `place` (đoán theo khách) · `manual` (người gán) · `none` |
| `zone_uncertain` | `true` = máy phải đoán. **Nêu lại cho người dùng**, đừng im lặng dùng |
| `waiting_picking` | `true` = xếp theo đơn, phiếu xuất chưa có |
| `procedure_required` | `none` · `customs` (khai hải quan) · `register` (đăng ký trước) · `both` |
| `procedure_ready` | Người điều phối đã xác nhận làm xong thủ tục chưa |
| `procedure_blocked` | `true` = **kế hoạch không xác nhận được** khi còn dòng này |
| `delivery_channel` | `company` · `pickup` · `express` · `grab` · `other` · `null` (không rõ) |
| `needs_truck` | `false` = điểm này đang chiếm một chỗ trên xe mà lẽ ra không cần |
| `extra_service_minutes` | Phút đứng **lâu hơn** điểm thường trong cụm (0 = như thường lệ) |
| | Ngoài ô này, lộ trình còn tự cộng phần đứng **theo số phiếu tại điểm**: 1 phiếu 4′ · 2–3 phiếu 15′ · 4 phiếu 22′ · từ 5 phiếu 30′ (định mức cụm đo trên điểm một phiếu, nên chỉ cộng phần dôi ra) |
| `driver_note` | Cổng vào, SĐT người nhận, đường khó — chuyển nguyên văn cho tài xế |
| `leg_km`, `leg_minutes` | Chặng từ điểm trước tới điểm này. `null` = điểm này thiếu toạ độ |
| `same_point` | `true` = cùng chỗ với dòng ngay trước (cách < 50 m, hoặc cùng địa chỉ khi thiếu toạ độ). Chặng 0 km / 0 phút — **nhiều đơn một điểm chỉ tính một lần**. Xếp các đơn cùng khách LIỀN NHAU thì mới được gộp |
| `arrive_offset_minutes`, `depart_offset_minutes` | Phút tính **từ lúc xe xuất phát** |
| `delivered` | Đã giao chưa — theo phiếu xuất đã hoàn tất, cập nhật mỗi giờ |
| `delivered_source` | `scan` = shipper quét tại điểm (giờ thật) · `odoo` = ai đó bấm trong Odoo, thường là bấm gộp cả xấp sau khi xe về. **Đừng đo giờ giấc bằng mốc `odoo`** — phần học lại định mức đã tự bỏ chúng |

Ở phần tóm tắt kế hoạch còn có `procedure_blocked_count` và `no_truck_count` — đếm sẵn để
không phải duyệt hết `lines[]` mới biết kế hoạch có xác nhận được không.

`zone_warning` báo khi kế hoạch **vượt trần điểm**, **dưới ngưỡng đáng chạy**, hoặc **gom
nhiều cụm**. Đây là cảnh báo, không phải lỗi — nhưng phải nêu lại cho người dùng.

Chuyến gom nhiều cụm vẫn tính đúng giờ: **mỗi điểm dùng định mức của cụm chính nó**,
chặng VƯỢT cụm tính theo km ÷ tốc độ + thời gian đứng (không có số đo cho chặng liên cụm),
chặng về lấy theo cụm của điểm cuối.

`total_minutes` gồm cả **chặng về kho** (`return_minutes`) khi cụm có khai: một chuyến chỉ
xong khi xe về tới kho, và với cụm xa thì chặng về đáng kể (Châu Đức 80 phút).

Giờ tới thật = giờ xuất phát bạn giả định + `arrive_offset_minutes`. Hệ thống không lưu giờ
xuất phát; buổi sáng/chiều bắt đầu mấy giờ là điều phải hỏi người dùng.

## 10. `GET /plans/<id>/vs-actual`

Đối chiếu chuyến đã chạy với kế hoạch của nó. **Đây là nguồn để sửa định mức** — không có
nó thì mọi con số trong `hlv.vtracking.zone` mãi là ước lượng ban đầu.

```json
{"summary": {"measured": 7, "on_time": 5, "late": 2, "early": 0,
             "mean_variance": 11, "mean_abs_variance": 14,
             "worst": {"planned": 96, "actual": 133, "variance": 37, "on_time": false}},
 "start_source": "received",
 "stops": [{"line_id": 88, "seq_no": 1, "reference": "WH/OUT/01234",
            "zone_name": "Nhơn Trạch", "planned": 40, "actual": 43, "variance": 3,
            "on_time": true, "delivered": true, "returned": false, "return_reason": null}],
 "plan": { ...tóm tắt kế hoạch... }}
```

| Khoá | Nghĩa |
|---|---|
| `planned`, `actual` | Phút **tính từ lúc xe xuất phát**, không phải giờ trong ngày |
| `variance` | `actual - planned`. **Dương = tới chậm hơn kế hoạch**. `null` = không đo được |
| `on_time` | Chênh trong 15 phút |
| `mean_variance` | Giữ dấu. Luôn dương ở một cụm = **định mức cụm đó quá lạc quan** |
| `mean_abs_variance` | Bỏ dấu. Mức **dao động** — định mức đúng trung bình mà dao động lớn thì vẫn không hứa giờ với khách được |
| `returned` | Đã tới nơi nhưng **không giao được**, hàng chở về kho |
| `start_source` | `received` (lúc hàng lên xe — tin được) · `done` (lúc giao điểm đầu — **thời lượng là cận dưới**) · `none` |

`measured: 0` nghĩa là chưa đối chiếu được điểm nào — khác hẳn "đo được và đúng y hẹn".
Đừng báo cáo trung bình khi `measured` bằng 0.

## 11. `POST /plans/<id>/refresh-actual` 🔒

Đọc lại số thực tế ngay thay vì chờ tác vụ nền (chạy mỗi giờ). Không sửa gì trong kế hoạch,
chỉ đọc lại từ phiếu giao và GPS. Trả về đúng dạng của `/vs-actual`.

## 12. `POST /estimate` — không ghi gì

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

Tính **đúng như kế hoạch thật**: mỗi điểm được suy cụm từ toạ độ (`stops[].zone_id`,
`zone_name`, `zone_uncertain`) và dùng định mức của cụm đó. Con số thử ở đây là con số sẽ
thấy trên kế hoạch khi tạo — nên so phương án bằng endpoint này là tin được.

## 13. `POST /plans` 🔒

```json
{"vehicle_id": 5, "date": "2026-09-19", "session": "morning", "start_place_id": 3}
```

Trả chi tiết kế hoạch + `created`. Đã có kế hoạch cho (xe, ngày, buổi) thì trả lại cái có
sẵn với `created: false` — **không phải lỗi**. Lỗi 422 khi xe chưa bật theo dõi, hoặc điểm
xuất phát chưa có toạ độ / chưa gắn kho.

Không truyền `start_place_id` thì lấy **điểm xuất phát mặc định của xe**
(`vehicles[].assignment.start_place_id` ở `/context`). Tài xế của kế hoạch mặc định là tài
xế gắn với xe (`assignment.driver_user_id`), hiển thị bằng `shipper_name`.

## 13b. `POST /plans/<id>/start` 🔒

`{"start_place_id": 3}` — đổi điểm xuất phát của kế hoạch **đã tạo**. Cần vì `POST /plans`
gặp kế hoạch có sẵn thì trả lại nguyên trạng. Lộ trình tự tính lại. Điểm phải có toạ độ và
gắn kho, nếu không trả 422.

## 14. `POST /plans/<id>/documents` 🔒

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

## 15. `POST /plans/<id>/notes` 🔒

Ghi **lý giải** của bạn lên kế hoạch. Không đổi lộ trình.

```json
{"reasoning": "Ưu tiên Long Thành vì 4/6 đơn hẹn hôm nay...",
 "excluded": [{"name": "DH125...", "reason": "Coherent chưa khai hải quan, trễ 26 ngày"},
              {"name": "DH126...", "reason": "Imarket gửi CPN, không cần xe"}]}
```

- `reasoning` → **chatter** của kế hoạch, kèm tên khoá API và dấu thời gian. Là nhật ký,
  gọi lại không ghi đè.
- `excluded` → ô **"Đơn bị loại và lý do"** trên form, hiện thành tab *AI cân nhắc*.
  **Ghi đè** ô cũ — nó là ảnh chụp của lần cân nhắc gần nhất.
- Gửi một trong hai cũng được. Gửi cả hai thì rõ nhất.

Đây là chỗ **bắt buộc dùng**: tờ kế hoạch in ra chỉ có danh sách điểm, không có câu "vì
sao không đi Coherent". Không ghi thì người điều phối không kiểm được bạn đúng hay sai.

## 16. `POST /plans/<id>/remove-lines` 🔒

`{"line_ids": [55]}` — **id dòng**, không phải id phiếu. Trả `removed_line_ids` + `plan`.
Id không thuộc kế hoạch này bị bỏ qua: đối chiếu `removed_line_ids` với thứ bạn gửi.

## 17. `POST /plans/<id>/resequence` 🔒

`{"line_ids": [56, 55, 57]}` — thứ tự mong muốn. Dòng không nêu giữ thứ tự tương đối và dồn
xuống cuối. Hoặc `{"strategy": "nearest"}` — hệ thống sắp theo "tới điểm gần nhất chưa ghé"
(điểm khởi đầu tốt, không phải tối ưu). Trả chi tiết kế hoạch sau khi sắp.

## 18. `POST /plans/<id>/state` 🔒

`{"action": "confirm"}` — một trong `confirm`, `back_to_draft`, `cancel`, `done`.
Kế hoạch `done` / `cancelled` không sửa được nữa (422).

## 19. `POST /geocode` 🔒

`{"address": "..."}` → `address_id`, `normalized_address`, `geo_state`, `latitude`,
`longitude`, `from_cache`. Tìm trong kho toạ độ trước; không có mới gọi geocoder ngoài —
**lượt gọi mới tốn tiền**, nên chỉ dùng khi thật sự cần toạ độ của một địa chỉ chưa từng
xuất hiện. Toạ độ rơi ngoài Việt Nam bị từ chối: `latitude`/`longitude` là `null`,
`geo_state = "failed"`.

---

# Dữ liệu nền — sửa địa chỉ, toạ độ, gộp trùng, thói quen, định mức, xe

Ba luật chung cho mọi endpoint dưới đây:

1. **Gộp trùng luôn hai bước.** `.../duplicates` chỉ để XEM đề xuất; `.../merge` gộp đúng
   các id được gửi. Không có lối "tự gộp hết". Đưa đề xuất cho người dùng duyệt trước.
2. **Tra toạ độ có thể tốn tiền** (Google tính theo lượt). Toạ độ `manual` (nhập tay) không
   bao giờ bị tra đè — gọi `.../geocode` lên bản `manual` trả 422.
3. **Sửa là ghi đúng ô được gửi.** Gửi `null` là xoá ô. Ô không nằm trong danh sách được
   sửa bị bỏ qua; không còn ô nào hợp lệ thì trả 422 kèm danh sách ô sửa được. Mọi thao tác
   ghi lên địa điểm để lại dòng `API (<tên khoá>): ...` trên chatter.

Toạ độ trong body nhận hai dạng: `{"coords": "10.7489, 106.9241"}` hoặc
`{"latitude": 10.7489, "longitude": 106.9241}`.

## 20. Kho toạ độ — `/addresses`

Kho toạ độ là bảng cache "chuỗi địa chỉ → toạ độ" mà kế hoạch dùng. Một dòng kế hoạch trỏ
tới đúng một bản ghi ở đây (`address_id`).

| Endpoint | Việc |
|---|---|
| `GET addresses` | Lọc: `search`, `geo_state` (`pending_review` / `confirmed` / `manual` / `failed`), `has_coords=0\|1`, `outside_vietnam=1`, `include_aliases=1`, `limit` (≤200), `offset` |
| `GET addresses/<id>` | Một bản ghi |
| `POST addresses/<id>` 🔒 | `{"coords": "..."}` → ghi tay (`manual`), hoặc `{"confirm": true}` → duyệt toạ độ máy tìm |
| `POST addresses/<id>/geocode` 🔒 | Tra lại toạ độ. **Tốn tiền** |
| `GET addresses/duplicates` | Nhóm nghi trùng |
| `POST addresses/merge` 🔒 | `{"keep_id": 5, "merge_ids": [7, 9]}` |

Mỗi bản ghi: `id`, `raw_address`, `normalized_address`, `latitude`, `longitude` (null nếu
rơi ngoài Việt Nam), `geo_state`, `geo_source`, `outside_vietnam`, `alias_of_id`,
`hit_count`, `last_used_at`, `plan_line_count`.

**Dò trùng** trả `{"group_count", "groups": [{"ids", "keep_id", "score", "addresses": [...]}]}`.
Hai địa chỉ bị coi là trùng khi **cả ba** đúng: giống chữ (Jaccard ≥ 0.75 sau khi bỏ từ hành
chính như "phường", "tỉnh"), **khớp hệt** các mã định danh (số nhà, số lô, chữ lô một ký
tự — "Lô D" khác "Lô N"), và toạ độ cách nhau ≤ 1 km. **Không bao giờ gộp chỉ vì trùng toạ
độ**: geocoder trả tâm KCN cho hàng chục công ty khác nhau. `keep_id` là bản gợi ý giữ (toạ
độ tin cậy nhất, dùng nhiều nhất) — người dùng được chọn bản khác.

**Gộp** không xoá: bản gộp thành **bí danh** (`alias_of_id`) của bản giữ, nên lần sau gặp lại
đúng chuỗi cũ vẫn ra toạ độ của bản giữ mà không tra lại. Dòng kế hoạch trỏ bản gộp được
chuyển sang bản giữ; bản giữ đang thiếu toạ độ thì lấy của bản gộp. Trả `keep_id`,
`merged_ids`, `plan_lines_moved`, `keep`.

## 21. Địa điểm — `/places`

Địa điểm là "nơi xe ghé": kho, khách, nhà cung cấp. Một khách có thể có nhiều địa điểm (hai
nhà máy). Thói quen khách gắn vào địa điểm.

| Endpoint | Việc |
|---|---|
| `GET places` | Lọc: `search` (tên / địa chỉ / tên khách), `type_code`, `zone_id`, `geo_state`, `has_coords=0\|1`, `no_zone=1`, `no_profile=1`, `no_partner=1`, `include_archived=1`, `limit`, `offset` |
| `POST places` 🔒 | Tạo. Bắt buộc `name`. `type_code` mặc định `customer` (còn `warehouse`, `partner`, `supplier`, `other`) |
| `GET places/<id>` | Một địa điểm kèm `profile` — mở được cả bản đã lưu trữ |
| `POST places/<id>` 🔒 | Sửa |
| `POST places/<id>/geocode` 🔒 | Tra lại toạ độ từ `address`. **Tốn tiền** |
| `POST places/<id>/confirm-geo` 🔒 | Duyệt toạ độ máy tìm |
| `GET places/duplicates` | Nhóm nghi trùng |
| `POST places/merge` 🔒 | `{"keep_id": 5, "merge_ids": [7]}` |

Ô sửa được: `name`, `partner_id`, `alias_partner_ids`, `zone_id`, `warehouse_id`, `address`,
`note`, `active`, cộng `type_code` và toạ độ. Địa điểm kiểu `warehouse` **phải** có `warehouse_id` — đó là
điều kiện để nó hiện làm điểm xuất phát trong `context`.

```json
POST places/12
{"type_code": "warehouse", "warehouse_id": 1, "coords": "10.7489944, 106.9241992"}
```

`alias_partner_ids` là **mã khách khác cùng điểm**. Cùng một công ty nhưng Odoo có nhiều mã
khách gốc (đo 22/09/2026: Summit Polymers là #132 và #21366) — mã không khai ở đây thì phiếu
ghi mã đó coi như khách chưa có điểm: không có cụm, không có thói quen. Gửi cả danh sách, nó
ghi đè (`null` hoặc `[]` là xoá hết). Chỉ khai mã GỐC; liên hệ con tự quy về công ty cha.

**Dò trùng** trả nhóm `{"ids", "keep_id", "reasons", "places"}`. `reasons`:
- `same_name` — cùng tên sau khi chuẩn hoá.
- `same_spot` — cách nhau < 50 m **và** tên này chứa tên kia.
- `same_customer` — cùng khách gốc. Dòng kế hoạch chỉ ghép với một địa điểm của khách, nên
  địa điểm thừa không bao giờ được dùng — nhưng **có thể là hai nhà máy thật**. Nhóm chỉ có
  lý do này thì phải hỏi người dùng trước khi gộp.

`keep_id` gợi ý: bản có thói quen khách → bản gắn kho → toạ độ đáng tin nhất.

**Gộp**: bản giữ được điền các ô đang trống từ bản gộp; thói quen khách được chuyển sang
(hoặc điền vào thói quen sẵn có); kế hoạch, xe, dòng kế hoạch trỏ bản gộp được chuyển sang
bản giữ; mã khách của bản gộp thành **mã phụ** của bản giữ; bản gộp bị **lưu trữ**, không xoá — gộp nhầm thì `POST places/<id> {"active": true}`.
Trả `keep_id`, `merged_ids`, `plans_moved`, `vehicles_moved`, `plan_lines_moved`,
`profiles_moved`, `keep`.

## 22. Thói quen khách

| Endpoint | Việc |
|---|---|
| `POST places/<id>/profile` 🔒 | Tạo hoặc sửa thói quen của địa điểm — chỉ ghi ô được gửi |
| `POST profiles/seed-known` 🔒 | Mồi các thói quen đã biết vào địa điểm khớp tên. Trả `created`, `updated`, `skipped` |

Ô: `procedure_required`, `delivery_method`, `default_vehicle_id`, `extra_service_minutes`,
`receiving_from`, `receiving_to` (giờ dạng số, 13.5 = 13:30), `payment_method`, `free_note`.
Giá trị hợp lệ của ô lựa chọn được liệt kê trong lỗi 422 nếu gửi sai.

## 23. Cụm tuyến — định mức

| Endpoint | Việc |
|---|---|
| `POST zones/<id>` 🔒 | Sửa `name`, `code`, `hub_to_first_minutes`, `median_leg_minutes`, `return_minutes`, `max_stops`, `min_stops_worth_trip`, `warehouse_id`, `note`, `active` |
| `POST zones/<id>/apply-calibration` 🔒 | Ghi đề xuất học từ thực tế vào định mức. 422 nếu chưa có đề xuất |
| `POST zones/recalibrate` 🔒 | Tính lại đề xuất ngay, không chờ cron hằng ngày. Trả mọi cụm |

Sửa định mức là đổi giờ ước của **mọi** kế hoạch nháp dùng cụm đó — nên cả ba trả
`{"before", "after"}` để nói lại được với người dùng mình vừa đổi gì. Mỗi cụm có
`calibration.{hub,leg,return}.{measured, samples, suggest}`.

## 24. Xe và tài xế

| Endpoint | Việc |
|---|---|
| `POST vehicles/<id>` 🔒 | Sửa chuyên chở + phân công của xe |
| `GET drivers` | Tài khoản có `shipper_name` — chọn được làm tài xế — kèm xe đang gắn |

Ô của xe (viết có hay không có tiền tố `dispatch_` đều được): `role` (`van` / `truck` /
`technical` / `motorbike`), `payload_kg`, `cargo_length_m`, `cargo_width_m`,
`cargo_height_m`, `max_item_length_m`, `max_pieces`, `note`, `driver_user_id`,
`start_place_id`. Một tài khoản chỉ gắn được một xe. Trả `capacity` và `assignment`
như trong `context`.

```json
POST vehicles/4
{"role": "van", "payload_kg": 1000, "driver_user_id": 27, "start_place_id": 12}
```

## 25. Yêu cầu của nhân viên — `/requests`

Nhân viên bán hàng bấm *Thao tác → Nhờ AI xếp lịch* trên đơn bán, viết mong muốn ("khách
xin nhận sáng mai trước 10h"). Odoo đẩy ngay một tin qua bus tới máy chạy worker; worker
gọi Claude, Claude dùng skill `xu-ly-yeu-cau-dieu-phoi` và trả lời qua các endpoint dưới.

| Endpoint | Việc |
|---|---|
| `GET requests` | Lọc `state` (mặc định `pending`, `all` xem hết), `limit`, `offset`. Sắp theo phiếu cũ trước |
| `GET requests/<id>` | Một phiếu |
| `POST requests/<id>/claim` 🔒 | `{"worker": "laptop-Luan"}` → `{"claimed": true\|false}` |
| `POST requests/<id>/answer` 🔒 | `{"verdict", "answer", "applied"}` |
| `POST requests/<id>/fail` 🔒 | `{"error": "..."}` |

Mỗi phiếu: `id`, `state`, `approved`, `request_type` + `request_type_label`, `message`,
`requester`, `created_at`, `waiting_minutes`, `sale_order_id`/`sale_order_name`,
`picking_id`, `plan_id`/`plan_name`/**`plan_state`**, `desired_date`, `desired_session`,
`verdict`, `applied`, `attempt_count`.

**Bắt buộc `claim` trước khi `answer`.** `claimed: false` nghĩa là máy khác đã nhận phiếu
đó — bỏ qua, đừng thử lại. `answer` gọi khi phiếu không ở trạng thái *AI đang xem* sẽ bị
từ chối 422: đó là chốt chặn để hai worker không trả lời chồng nhau.

`verdict` là một trong `feasible` (được), `conditional` (được nếu…), `not_feasible`
(không được), `info` (chỉ trả lời câu hỏi). `answer` là chữ thường, xuống dòng bình thường;
dòng VIẾT HOA kết thúc bằng `:` thành tiêu đề đậm. Người gửi nhận thông báo ngay khi có
câu trả lời.

`applied: true` **chỉ** khi đã thật sự sửa kế hoạch xong → phiếu chuyển *Xong*.
`applied: false` → phiếu ở *AI đã trả lời*, chờ người điều phối bấm *Duyệt* hoặc *Từ chối*.

**Kế hoạch đã chốt thì không sửa.** Thấy `plan_state: "confirmed"` thì chỉ mô tả phương án.
Người điều phối bấm *Duyệt* → Odoo đưa kế hoạch về nháp (do người bấm, không phải AI) và
phiếu quay lại `pending` với `approved: true`; lúc đó mới được sửa.

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
