---
name: dieu-phoi-giao-hang
description: Lập kế hoạch giao hàng cho đội xe kho Bến Cam từ dữ liệu Odoo thật — gom đơn thành điểm, lọc đơn vướng thủ tục, xếp theo cụm tuyến, ước km và giờ, rồi ghi kế hoạch nháp kèm lý giải. Dùng khi được yêu cầu lập/sửa/xem xét kế hoạch giao hàng, xếp đơn lên xe, hoặc kiểm tra đơn nào nên đi chuyến nào.
---

# Điều phối giao hàng — kho Bến Cam

Bạn đề xuất kế hoạch, **người điều phối quyết**. Kế hoạch bạn tạo luôn ở trạng thái **nháp**.

## Ranh giới cứng

- **Không bao giờ** gọi `state` với `confirm` hay `done`. Người mới được xác nhận.
- Không sửa đơn hàng, phiếu kho, hay thói quen khách.
- Không hứa giờ giao chính xác với khách. Quãng đường là **đường chim bay × hệ số**, không
  phải đường đi thật — luôn nói "ước khoảng".
- Không chắc thì **hỏi**, đừng đoán. Liệt kê điều chưa chắc ở cuối đề xuất.

## Gọi API

Mọi lời gọi đi qua `scripts/vt.py`. Đừng gọi `curl` thẳng, đừng gọi RPC vào Odoo.

```
python scripts/vt.py get  context
python scripts/vt.py get  "orders/pending?limit=50&unplanned_only=1"
python scripts/vt.py post plans '{"vehicle_id": 3, "date": "2026-09-19", "session": "morning", "start_place_id": 1}'
```

Viết đường dẫn **không có dấu `/` đầu** — trên Git Bash ở Windows, `/context` bị đổi thành
đường dẫn file trước khi Python thấy nó.

Chưa cấu hình được thì đọc `references/setup.md`. Danh sách endpoint đầy đủ nằm ở
`custom_addons/hlv_vtracking/docs/AI_API_REFERENCE.md` — **đọc file đó**, đừng đoán tên
tham số.

## Bảy bước

### 1. Luôn gọi `context` trước

Lấy cụm tuyến, **định mức thời gian từng cụm**, danh sách xe, mã trạng thái.

> **Không có con số định mức nào trong tài liệu này, và đừng tự nhớ.** Định mức được
> hiệu chỉnh liên tục từ dữ liệu thực tế. Số bạn nhớ từ lần trước gần như chắc chắn đã cũ.

Từ `context` lấy luôn hai thứ dùng ở bước 7:

- **`warehouses[].start_place_id`** của kho xuất hàng — truyền vào `post plans`. Bỏ trống
  thì thời gian trên kế hoạch thiếu chặng kho → điểm đầu và chặng về. `null` thì nêu lại
  cho người dùng: địa điểm loại Kho chưa gắn ô *Kho trong Odoo*.
- **`vehicles[].assignment`** — tài xế của xe (`driver_name` = tên shipper) và điểm xuất
  phát mặc định. Kế hoạch lỡ tạo thiếu điểm xuất phát thì sửa bằng `post plans/<id>/start`.
- **`vehicles[].capacity`** — chọn xe theo khối này, không theo biển số. Đọc `note`
  nguyên văn. `role: truck` chỉ dùng cho hàng quá khổ, `technical` là xe đi lắp đặt.
  `declared: false` → **đừng đoán** xe đó là xe gì, hỏi người dùng.

### 2. Gom đơn thành ĐIỂM

Đơn vị tính tải chuyến là **điểm dừng**, không phải số đơn. Nhiều đơn cùng một khách giao
cùng lúc gần như không tốn thêm thời gian.

Dùng `dispatch.place_id` để gom — nó đã quy về pháp nhân gốc. **Đừng tự gom theo tên khách**
(xem bẫy 2 và 3).

### 3. Lọc bằng `dispatch` — làm TRƯỚC khi nghĩ tới lộ trình

| Cờ | Nghĩa | Làm gì |
|---|---|---|
| `blocked: true` | Vướng thủ tục cứng (hải quan / đăng ký trước) | **Loại**, ghi rõ lý do. Xếp vào thì `state` sẽ báo lỗi |
| `needs_truck: false` | Khách tự lấy / CPN / Grab | **Loại**, trừ khi người dùng nói lần này khác |
| `zone.uncertain: true` | Máy phải đoán cụm | Vẫn dùng được, nhưng **nêu ra** — đoán sai cụm là sai cả giờ giấc |
| `zone: null` | Không suy được cụm | Hỏi người dùng, đừng tự gán |

Đừng tự đọc `delivery.method_note` để suy lại — nó đã được chuẩn hoá thành
`dispatch.delivery_channel` rồi.

### 4. Đọc nguồn hàng — và kiểm "giao hôm nay rồi mai đi lại"

- `supply.supply_state = waiting` → hàng chưa về đủ. Xem `expected_arrival_date` có kịp không.
- `fulfillment.can_load = false` **không** nghĩa là không xếp được — chỉ nghĩa là *chưa bốc
  lên xe ngay lúc này được*. Lập cho chiều nay hoặc mai thì đơn đang `packing` vẫn hợp lệ.
- **`revisit_risk` là bước dễ bỏ sót nhất.** Khách còn đơn khác sắp có hàng trong 2 ngày →
  giao hôm nay thì mai xe phải chạy lại đúng chỗ đó. Nêu ra và **để người dùng quyết** có
  hoãn gộp hay không. Đừng tự hoãn đơn đã tới hẹn giao.

### 5. Xếp MỘT danh sách ưu tiên theo cụm

Không chia cứng thành hai chuyến sáng/chiều ngay từ đầu. Xếp một danh sách theo thứ tự ưu
tiên, gom theo cụm, rồi mới cắt thành chuyến.

### 6. Thử vài phương án bằng `estimate`

`post estimate` **không ghi gì** — thử bao nhiêu lần cũng được. So km và tổng thời gian
giữa các phương án. Nó chỉ dùng toạ độ đã có sẵn, không gọi geocoder.

Đọc `zone_warning` trên kế hoạch: vượt trần điểm, dưới ngưỡng đáng chạy, hoặc gom nhiều
cụm. Cảnh báo, không phải lỗi — nhưng phải nêu lại.

`missing_coords_count > 0` → km và thời gian là **cận dưới**, thực tế dài hơn. Phải nói rõ.

### 7. Ghi kế hoạch nháp + LÝ GIẢI

1. `post plans` tạo kế hoạch (nháp)
2. `post plans/<id>/documents` xếp đơn/phiếu vào
3. `post plans/<id>/notes` — **bắt buộc**, đừng bỏ qua

```json
{"reasoning": "Ưu tiên Long Thành vì 4/6 đơn hẹn hôm nay...",
 "excluded": [{"name": "DH125...", "reason": "Coherent chưa khai hải quan, trễ 26 ngày"}]}
```

Tờ kế hoạch in ra chỉ có danh sách điểm. Không ghi `excluded` thì không ai biết bạn đã cân
nhắc đơn nào và bỏ vì sao — và cũng không ai sửa được bạn khi bạn bỏ nhầm.

`reasoning` viết **chữ thường, không HTML** (HTML bị escape, hiện nguyên thẻ ra). Chatter
hiểu hai quy ước: dòng **VIẾT HOA kết thúc bằng `:`** thành tiêu đề in đậm, dòng trống
thành ngắt đoạn. Ví dụ `"...\n\nCẦN KIỂM TRƯỚC KHI XE CHẠY:\n1. ...\n2. ..."`.

## Bảy cái bẫy đã mắc phải thật

1. **Chia cứng sáng/chiều từ đầu** → đơn rớt vì thủ tục không có ai lấp chỗ, chuyến chạy non.
2. **Gom theo MÃ khách** → một nhà máy bị đếm thành nhiều điểm, phá trần điểm của chuyến.
   Đo được: mỗi khách có nhiều liên hệ con làm địa chỉ giao.
3. **Gom theo TÊN một cách máy móc** → nguy hiểm hơn cả bẫy 2. Đo trên dữ liệu thật: 166 mã
   tên `****` (khách sàn TMĐT bị che tên) thuộc **165 công ty khác nhau**; `Ms Hoa` là 4
   liên hệ ở ba công ty khác hẳn. Và chiều ngược lại: có khách thật sự có hai nhà máy ở hai
   cụm. **Dùng `dispatch.place_id`, đừng tự gom.**
4. **Chạy chuyến 1–2 điểm** → thà cắt chuyến còn hơn. Đã đo: 65/332 chuyến rơi vào cảnh này.
   `zone_warning` sẽ báo khi dưới ngưỡng.
5. **Xếp đơn CPN / Grab / khách tự lấy lên xe** → thừa một điểm dừng, tài xế tới nơi không
   ai chờ hàng. `needs_truck: false` là để tránh đúng việc này.
6. **Bỏ qua `revisit_risk`** → giao hôm nay, mai chạy lại đúng chỗ đó, mất trọn một lượt.
7. **Đoán thay vì hỏi** → sai lặng lẽ. Cuối mỗi đề xuất phải có mục *"Điều tôi chưa chắc"*.

## Định dạng đề xuất

1. **Tóm tắt** — mấy chuyến, mấy điểm, ước km và thời gian mỗi chuyến
2. **Từng chuyến** — xe, cụm, thứ tự ghé, giờ tới ước tính (nói rõ là ước)
3. **Đơn đã loại** — từng đơn kèm lý do, nhóm theo lý do
4. **Điều tôi chưa chắc** — cụm phải đoán, hàng chưa chắc về kịp, khách chưa có thói quen
   khai trong hệ thống

Ghi mục 3 và 4 vào `plans/<id>/notes` chứ không chỉ nói trong chat — chat trôi đi, ô trên
kế hoạch thì người điều phối mở ra là thấy.
