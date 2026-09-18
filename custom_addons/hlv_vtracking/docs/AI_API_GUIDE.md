# V-Tracking AI API — Hướng dẫn cho AI lập kế hoạch giao hàng

Tài liệu này viết cho **một AI agent** (Claude) được giao việc: đọc tình hình đơn hàng, kho,
xe của công ty rồi **đề xuất hoặc lập kế hoạch giao hàng**. Tra cứu chi tiết từng endpoint:
xem [AI_API_REFERENCE.md](AI_API_REFERENCE.md).

---

## 1. Bạn đang làm việc với cái gì

Công ty bán hàng công nghiệp, giao bằng **xe của công ty** từ các **kho** tới khách. Một
**kế hoạch giao hàng** = **một xe** chở một loạt điểm giao trong **một buổi của một ngày**.

```
đơn MUA về kho ──► đơn BÁN đủ hàng ──► kho soạn: PICK → PACK → OUT ──► xếp lên XE ──► giao
   (supply)                               (fulfillment)                (plan)
```

Việc của bạn nằm ở mũi tên cuối: quyết định **chứng từ nào lên xe nào, buổi nào, theo thứ tự
nào**. Nhưng để quyết đúng, bạn phải đọc được cả chuỗi phía trước — một đơn hàng chưa về
thì xếp lên xe cũng không giao được.

## 2. Kết nối

| | |
|---|---|
| Base URL | `https://<odoo-host>/api/v1/ai` |
| Xác thực | header `X-API-Key: <khoá>` |
| Định dạng | JSON, UTF-8. `POST` gửi body JSON với `Content-Type: application/json` |
| Quyền ghi | Khoá phải bật **"Cho phép ghi"** mới gọi được các endpoint `POST` sửa dữ liệu |

Mọi phản hồi cùng một khung:

```json
{"success": true,  "data": { ... }}
{"success": false, "error": {"code": "BUSINESS_RULE", "message": "..."}}
```

**Quy ước dữ liệu** — áp cho mọi endpoint:

- Thời điểm: ISO 8601 **UTC** có hậu tố `Z` (`2026-09-18T02:30:00Z`). Giờ Việt Nam = UTC+7.
- Ngày: `YYYY-MM-DD`, hiểu theo **giờ Việt Nam**.
- `null` nghĩa là **chưa có dữ liệu** — khác với `0`. Đừng coi `null` là 0.
- Tiền: số thực, đơn vị VND, chưa định dạng.

## 3. Quy trình làm việc nên theo

### Bước 1 — Nắm bối cảnh (một lần mỗi phiên)

`GET /context` → kho, xe, các buổi, **`zones`** (định mức từng cụm), bảng giai đoạn kho, và
**`business_rules`** — danh sách luật nghiệp vụ. **Đọc `business_rules` trước tiên**: nó là
bản mới nhất, tài liệu này có thể cũ hơn.

**`zones` là nguồn định mức duy nhất.** Mỗi cụm có thời gian riêng đo từ chuyến thật —
Nhơn Trạch ra khỏi kho 40 phút, Long Thành 57 phút. Con số này được sửa lại sau mỗi lần đối
chiếu kế hoạch với thực tế, nên đừng nhớ nó giữa các phiên; gọi lại `/context` mỗi lần.

Mỗi cụm còn có `max_stops` (trần điểm, **mềm** — vượt chỉ cảnh báo) và
`min_stops_worth_trip` (**dưới ngưỡng này thì đừng chạy chuyến** — gộp sang chuyến khác
hoặc gửi chuyển phát nhanh).

### Bước 2 — Xem xe

`GET /fleet?date=<ngày định lập>` → mỗi xe: đang ở đâu, trạng thái, đã có kế hoạch gì trong
ngày đó, và **`free_sessions`** — những buổi còn trống.

- `is_stale: true` = hơn 30 phút không có tin GPS. Vị trí có thể đã cũ; xe vẫn lập kế hoạch
  được, nhưng đừng suy luận gì từ vị trí của nó.
- `free_sessions: []` = xe đã kín ngày đó.

### Bước 3 — Xem cái gì cần giao

Hai nguồn, dùng cả hai:

- `GET /pickings/ready?warehouse_id=` → phiếu xuất **xếp được ngay** (kho đã đóng gói xong).
  Đây là nguồn ưu tiên: chắc chắn có hàng.
- `GET /orders/pending?warehouse_id=&unplanned_only=1` → **mọi** đơn còn phải giao, kể cả
  đơn kho chưa soạn xong và đơn hàng chưa về. Dùng khi lập kế hoạch cho **ngày mai trở đi**.

### Bước 4 — Đọc kỹ từng đơn đáng ngờ

Với mỗi đơn định xếp, kiểm bốn thứ (đều có sẵn trong `/orders/pending`):

| Khối | Câu hỏi | Dừng lại khi |
|---|---|---|
| `supply` | Hàng về chưa? | `supply_state = "waiting"` và `expected_arrival` **sau** ngày định giao |
| `fulfillment` | Kho soạn tới đâu? | lập cho **hôm nay** mà `can_load = false` |
| `delivery.method_note` | Giao bằng cách nào? | ghi `GỬI CPN`, `BOOK GRAB`, `KHÁCH GHÉ LẤY`… → **không đi xe công ty** |
| `latest_note` | Có ai dặn gì không? | lời dặn mâu thuẫn với ngày định giao |

Cần chắc hơn thì `GET /orders/<id>` (đủ dòng hàng, từng phiếu kho, từng đơn mua, 15 tin
chatter gần nhất) hoặc `GET /orders/<id>/chatter` (toàn bộ hội thoại).

### Bước 5 — Thử phương án trước khi ghi

`POST /estimate` tính km và thời gian của một lộ trình **giả định**, **không ghi gì**. Gọi
bao nhiêu lần cũng được và không tốn tiền (chỉ dùng toạ độ đã có sẵn). Dùng nó để so:
"6 điểm này lên một xe hay chia hai xe", "thứ tự nào ngắn hơn".

### Bước 6 — Ghi kế hoạch

1. `POST /plans` → tạo kế hoạch (xe, ngày, buổi, `start_place_id` của kho xuất phát).
2. `POST /plans/<id>/documents` → xếp `picking_ids` và/hoặc `sale_order_ids`.
3. `POST /plans/<id>/resequence` → sắp thứ tự ghé (tự gửi danh sách, hoặc
   `{"strategy": "nearest"}`).
4. `GET /plans/<id>` → **đọc lại** kết quả: km, thời gian, giờ tới từng điểm.
5. `POST /plans/<id>/state` `{"action": "confirm"}` — **chỉ khi được người dùng cho phép
   chốt**. Mặc định để kế hoạch ở `draft` cho người điều phối duyệt.

Mọi thao tác ghi được ghi lại trên chatter của kế hoạch kèm tên khoá API — người điều phối
thấy được chính xác bạn đã làm gì.

## 4. Những điều dễ hiểu sai

**Phiếu hay đơn?** Xếp bằng `picking_id` khi đã có phiếu OUT sẵn sàng. Xếp bằng
`sale_order_id` khi kho chưa soạn — dòng kế hoạch ở trạng thái `waiting_picking`, và khi kho
tạo phiếu OUT thì hệ thống **tự gắn** phiếu vào. Đừng xếp cả đơn lẫn phiếu của cùng đơn đó.

**`can_load = false` không có nghĩa là không xếp được.** Nó chỉ nói *chưa bốc lên xe ngay
lúc này được*. Lập kế hoạch cho chiều nay hoặc ngày mai thì đơn đang `packing` vẫn hợp lệ.

**Hàng chưa về ≠ không xếp được.** Nếu `expected_arrival` là sáng mai mà bạn lập kế hoạch
chiều mai thì được. Nhưng hãy **nói rõ rủi ro** trong phần trình bày với người dùng:
"DH123 phụ thuộc đơn mua DMH456 dự kiến về 09:00".

**Quãng đường KHÔNG phải đường đi thật.** Nó là đường chim bay × hệ số đường bộ
(`route_params.road_factor`). Dùng để **so sánh phương án**. Đừng báo cho người dùng như giờ
giao chính xác; hãy nói "ước khoảng".

**`zone_uncertain = true`** = hệ thống phải **đoán** cụm cho điểm đó: hoặc điểm mẫu gần
nhất ở xa, hoặc chưa có toạ độ nên phải suy theo khách. Định mức thời gian của cả kế hoạch
dựa vào cụm, nên đoán sai cụm là sai cả giờ giấc. Nêu lại cho người dùng, đừng im lặng dùng.

**`missing_coords_count > 0`** = có điểm chưa tra được toạ độ. Khi đó `distance_km` và
`total_minutes` là **cận dưới** — thực tế dài hơn. Phải nêu điều này khi báo cáo.

**Khác kho.** Xe xuất phát từ kho nào chỉ nên chở hàng của kho đó. So `warehouse_id` của
chứng từ với `start.warehouse_id` của kế hoạch. API **không chặn** việc xếp khác kho (có
chuyến gom hai kho thật) — bạn phải tự để ý.

**Cân nặng thiếu dữ liệu.** `load.weight_coverage` thường thấp hơn 1.0 rất nhiều: đa số sản
phẩm chưa khai cân nặng. Coi `total_weight_kg` là cận dưới; dựa thêm vào `line_count`,
`total_qty`, `package_count` và mô tả dòng hàng để đoán xe có chở nổi không. **API không
biết tải trọng của xe** — hỏi người dùng khi nghi ngờ.

**`rejected` không phải lỗi.** `POST /documents` xếp được cái nào thì xếp, cái không xếp
được trả về trong `rejected` kèm `reason`:

| `reason` | Nghĩa | Nên làm gì |
|---|---|---|
| `already_planned` | Chứng từ đã nằm trong kế hoạch khác | Muốn chuyển xe: `remove-lines` ở kế hoạch cũ trước |
| `order_closed` | Đơn bán đã khoá sổ hoặc đã huỷ | Bỏ qua, không còn gì để giao |

## 5. Mã lỗi

| HTTP | `code` | Nghĩa |
|---|---|---|
| 400 | `BAD_PARAM` / `BAD_DATE` / `BAD_JSON` | Tham số sai — sửa request |
| 401 | `UNAUTHORIZED` | Khoá API sai hoặc đã thu hồi |
| 403 | `WRITE_NOT_ALLOWED` | Khoá chỉ được đọc — báo người dùng bật "Cho phép ghi" |
| 404 | `NOT_FOUND` | Không có bản ghi, hoặc bản ghi thuộc công ty khác |
| 422 | `BUSINESS_RULE` | Luật nghiệp vụ từ chối — **đọc `message`**, nó nói rõ vì sao |
| 500 | `SERVER_ERROR` | Lỗi máy chủ — dừng lại và báo người dùng, đừng thử lại liên tục |

Gặp `422` thì **đừng thử lại y nguyên**: nguyên nhân nằm ở dữ liệu (kế hoạch đã khoá, xe
chưa bật theo dõi…), thử lại sẽ ra đúng lỗi đó.

## 6. Cách trình bày đề xuất với người dùng

Khi được hỏi "lên kế hoạch giao ngày X", hãy trả lời theo khung:

1. **Tóm tắt**: bao nhiêu đơn cần giao, bao nhiêu xe trống, đề xuất mấy chuyến.
2. **Từng chuyến**: xe · buổi · kho xuất phát · danh sách điểm theo thứ tự · ước km và thời gian.
3. **Đơn KHÔNG xếp và lý do**: chờ hàng về (đơn mua nào, về khi nào), kho chưa soạn, giao
   bằng CPN/Grab, có lời dặn hoãn.
4. **Rủi ro**: điểm thiếu toạ độ, đơn phụ thuộc hàng về sát giờ, chuyến quá dài.
5. **Hỏi xác nhận** trước khi ghi — trừ khi người dùng đã bảo cứ làm.

Đừng giấu đơn bị loại. Người điều phối cần biết bạn **đã cân nhắc** đơn đó và vì sao bỏ,
chứ không phải tự phát hiện ra nó bị sót.
