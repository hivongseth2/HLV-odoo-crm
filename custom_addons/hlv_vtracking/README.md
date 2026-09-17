# V-Tracking (`hlv_vtracking`)

Theo dõi định vị đội xe qua **vTracking 2.0 Open API** (bản tài liệu 1.0.3).

Module **độc lập**, chỉ phụ thuộc `fleet` (Đội xe) của Odoo. Không dính tới điều phối
giao hàng.

---

## Ranh giới quan trọng nhất

> **Chỉ xe bật cờ "Theo dõi vTracking" trong Đội xe mới được đồng bộ, mới hiện trên bản
> đồ, và mới trả ra API.**

Tài khoản vTracking có thể chứa xe của pháp nhân khác. Cờ này là thứ duy nhất quyết định
module nhìn thấy gì — không có tham số nào nới được nó, kể cả từ API ngoài.

---

## Quyền

| Nhóm | Thấy được gì |
|---|---|
| **Xem bản đồ đội xe** (`group_vtracking_user`) | Menu V-Tracking, bản đồ, danh sách xe, lịch sử vị trí. Không sửa được gì |
| **Quản trị V-Tracking** (`group_vtracking_manager`) | Thêm: bật/tắt theo dõi xe, cấu hình kết nối, cấp khoá API |

Cấp ở **Cài đặt > Người dùng & Công ty > Người dùng**, mở user, mục **V-Tracking**.

Tài khoản quản trị được gán nhóm quản trị sẵn lúc cài. Người khác thì **không tự có** —
Odoo không tự thêm ai vào nhóm của module mới, nên ai không thấy menu V-Tracking là do
chưa được cấp nhóm.

## Bật lần đầu

1. Cài module. Menu **V-Tracking** xuất hiện (với tài khoản đã có nhóm ở trên).
2. **V-Tracking > Cấu hình > Kết nối vTracking**: điền địa chỉ máy chủ và API key do
   vTracking cấp, bấm **Kiểm tra kết nối**.
3. **V-Tracking > Xe theo dõi**: bỏ bộ lọc "Đang theo dõi" để thấy cả đội, bật cột
   **Theo dõi vTracking** cho xe cần giám sát.
4. Mở một xe bất kỳ, bấm **Đồng bộ ngay**. Thông báo sẽ nói rõ xe nào ghép được, biển số
   nào có trên vTracking mà chưa khai trong Đội xe, và xe nào khai rồi mà vTracking không
   trả về.
5. Bật hai tác vụ nền trong **Cài đặt > Kỹ thuật > Tác vụ nền** (mặc định **tắt** để
   module cài xong không tự gọi ra ngoài khi chưa có API key):
   - *V-Tracking: cập nhật vị trí đội xe* — 10 phút/lần.
   - *V-Tracking: kéo hành trình ngày hôm trước* — 1 lần/ngày.

   Tác vụ dọn bản tin quá hạn đã bật sẵn vì nó không gọi ra ngoài.

### Nếu "Kiểm tra kết nối" báo lỗi chứng chỉ SSL

Đã kiểm chứng chỉ của host mặc định ngày **17/09/2026**:

```
Subject : CN=*.innoway.vn
Issuer  : Sectigo RSA Domain Validation Secure Server CA
SAN     : *.innoway.vn, innoway.vn   (không có IP nào)
Hiệu lực: 08/03/2023 → 07/03/2024    ← ĐÃ HẾT HẠN
```

Chứng chỉ là **thật** (Sectigo cấp), không phải tự ký. Nhưng hai thứ cùng sai: nó cấp cho
tên miền chứ không cho IP, **và** nó đã hết hạn hơn hai năm. Vì vậy đổi sang gọi bằng tên
miền cũng không cứu được.

→ Hiện chỉ có một cách chạy được: **tắt "Kiểm tra chứng chỉ SSL"** trong cấu hình, chấp
nhận là không xác thực được máy chủ. Đồng thời yêu cầu vTracking gia hạn chứng chỉ và cấp
một tên miền — khi họ làm xong thì bật lại.

### Nếu báo HTTP 403 kèm chữ "nginx"

Phản hồi đó đến từ **proxy**, không phải từ ứng dụng vTracking (ứng dụng từ chối key thì
trả JSON). Thường là IP public của máy chủ Odoo chưa nằm trong danh sách cho phép của
vTracking. Đổi API key bao nhiêu lần cũng vô ích — phải hỏi vTracking về whitelist IP.

Module phân biệt sẵn hai trường hợp này và nói rõ nên đi hỏi phía nào.

---

## Bản đồ

**V-Tracking > Bản đồ đội xe.** Danh sách xe bên trái, ghim trên bản đồ, tự tải lại mỗi
30 giây.

Nền bản đồ mặc định là OpenStreetMap — không cần khoá API. Đổi nhà cung cấp chỉ cần sửa
hai ô *Nguồn tile* và *Ghi công* trong cấu hình, không phải sửa code.

Thư viện Leaflet nạp từ `unpkg.com` khi mở màn hình. Mạng công ty chặn CDN thì bản đồ
không vẽ được nhưng **danh sách xe vẫn dùng bình thường**, và màn hình nói rõ lý do.

Màu ghim: xanh lá = đang chạy · vàng = dừng · xanh dương = đỗ · xám = mất tín hiệu hoặc
quá 30 phút không có tin · tím = GPS kém.

---

## API cho ứng dụng ngoài

Cấp khoá tại **V-Tracking > Cấu hình > Khoá API**. Mỗi ứng dụng một khoá riêng — ứng dụng
nào rò rỉ thì thu hồi đúng khoá đó.

Gửi khoá ở header `X-API-Key`. Mọi endpoint trả về cùng một khung:

```json
{"success": true,  "data": {...}}
{"success": false, "error": {"code": "...", "message": "..."}}
```

### `GET /api/v1/fleet/vehicles`

Danh sách xe đang theo dõi kèm vị trí gần nhất. Tham số tuỳ chọn: `plate` (khớp một
phần), `status` (`run`/`stop`/`park`/`offline`/`badgps`).

**Không gọi sang vTracking** — trả về đúng những gì tác vụ nền đã đồng bộ. Ứng dụng gọi
dồn dập cũng không làm tài khoản vTracking dính 429.

```bash
curl -H "X-API-Key: <khoá>" "https://odoo.congty.vn/api/v1/fleet/vehicles"
```

### `GET /api/v1/fleet/vehicles/<id>/journey`

Hành trình một xe trong một ngày. Tham số: `date` (YYYY-MM-DD, mặc định hôm nay),
`source`:

- `stored` (**mặc định**) — đọc lịch sử đã lưu trong Odoo. Nhanh, không tốn lượt gọi.
- `live` — hỏi thẳng vTracking. Dùng cho ngày hôm nay khi tác vụ nền chưa chạy.

Mặc định là `stored` có chủ ý: để một ứng dụng chạy vòng lặp không vô tình bắn hàng loạt
request sang vTracking và làm khoá bị chặn.

### `GET /api/v1/fleet/map-config`

Nguồn tile bản đồ, để ứng dụng ngoài vẽ cùng nền bản đồ với Odoo.

---

## Cấu trúc code

Màn cấu hình là một form của **`res.company`**, không phải `res.config.settings`. Lý do:
action của `res.config.settings` luôn được Odoo mở trong app Cài đặt và **thay chỗ trang
Cài đặt chung** — bấm menu của module này lại làm mất màn hình cài đặt gốc.

| Thư mục | Được làm gì | Không được làm gì |
|---|---|---|
| `tools/` | Hàm thuần: chuẩn hoá biển số, đổi thời gian, bóc payload | Không `env`, không mạng, không side effect |
| `services/vtracking_client.py` | Nói HTTP với vTracking, phân trang, lùi dần khi 429 | Không biết Odoo là gì |
| `services/vtracking_sync.py` | Nối hai lớp trên, ghi vào Odoo | — |
| `models/`, `controllers/` | Mô hình dữ liệu, giao diện, API | Không chứa hàm dùng chung |

Ranh giới này để: gọi thử client từ shell mà không cần dựng env, và test thuật toán trong
`tools/` mà không cần Odoo.

---

## Lưu trữ

`hlv.vtracking.position` giữ từng bản tin vị trí. Một xe chạy cả ngày sinh hơn nghìn bản
ghi, nên bảng chỉ giữ trong thời hạn khai ở cấu hình (**mặc định 30 ngày**) và có tác vụ
dọn chạy hằng ngày. Để thời hạn 0 là giữ vĩnh viễn — bảng sẽ phình rất nhanh.

---

## Giới hạn của chính API vTracking

Tài liệu 1.0.3 chỉ có **2 endpoint**, và **không có**:

- Webhook / push — mọi thứ "realtime" đều là poll theo chu kỳ.
- Geofence, gán tài xế, gửi lệnh xuống thiết bị — API chỉ đọc.
- Lịch sử nhiều xe một lần — mỗi xe một lời gọi.
- **Lịch sử cảm biến** (`acc`, `door`) — chỉ đọc được ở thời điểm hiện tại, không truy
  ngược được. Muốn biết cửa thùng mở lúc mấy giờ thì phải tự poll và tự lưu.
- Hạn mức request cụ thể — chỉ biết là có mã 429.

Một điều nữa đọc ra từ ví dụ trong tài liệu: **thiết bị gửi rất thưa khi xe đỗ** (hai bản
ghi liền nhau cách nhau 145 phút). Đừng suy ra thời gian dừng bằng cách đếm số bản tin.

---

## Chưa làm

- Nối dữ liệu GPS với kế hoạch giao hàng (đối chiếu kế hoạch ↔ thực tế, hiệu chỉnh định
  mức cụm tuyến). Việc đó thuộc một module cầu nối riêng — xem
  `plan/ke-hoach-module-vtracking.md`.
- Xem lại hành trình một ngày trên bản đồ (hiện chỉ có danh sách bản tin trong form xe).
- Thông báo khi có cảnh báo lái quá giờ — dữ liệu đã lấy về, chưa đẩy ra ai.
