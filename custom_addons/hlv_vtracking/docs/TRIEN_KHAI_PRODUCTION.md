# Đưa V-Tracking lên production

Tài liệu cho người triển khai. Làm theo thứ tự — mỗi bước đều là điều kiện của bước sau.

Nguyên tắc chung: **toạ độ, điểm giao, thói quen khách và định mức đều là dữ liệu trong cơ
sở dữ liệu, không đi theo module.** Cài module lên production chỉ được cái khung rỗng; số
liệu phải nạp lại từ đúng những file dưới đây. Làm ở staging bao nhiêu lần cũng không thay
production được gì.

---

## 0. Ba file phải có trong tay

| File | Ở đâu | Dùng cho bước |
|---|---|---|
| `map2.json` | `C:\HLV\data\dieu-phoi-ben-cam\map2.json` | 3 — nhập 86 điểm giao kèm cụm và toạ độ người ghim |
| `khach.json` | `C:\HLV\data\HLV-dieu-phoi-kho-ben-cam-IT-20260922\HLV-dieu-phoi-kho-ben-cam\skills\dieu-phoi-ben-cam\references\khach.json` | 6 — luật khách: thông quan, đăng ký trước, giờ nhận, cách trả tiền |
| khoá API Google Maps | Google Cloud Console của công ty | 2 — tra toạ độ cho địa chỉ mới |

Cả hai file JSON **không nằm trong repo và không được commit** — chúng là dữ liệu khách
hàng. Giữ chúng ở ổ đĩa nội bộ, copy sang máy người triển khai khi cần.

---

## 1. Cài module

Module phụ thuộc: `fleet`, `base_geolocalize`, `hlv_geo_utils`, `sale_stock`, `sales_team`,
`purchase_stock`, `hlv_barcode_shipper`. Python cần `requests` và `pytz`.

```
git push <remote> <nhánh production>
```

**Bẫy đã gặp thật:** odoo.sh chỉ chạy *update* module khi **số phiên bản trong
`__manifest__.py` đổi**. Push mà không đổi phiên bản thì server khởi động lại với code mới
nhưng **không đụng vào cơ sở dữ liệu** — field mới có trong registry còn bảng thì chưa có,
và mọi thứ chạm tới field đó trả về lỗi 500. Đổi phiên bản trước khi push, hoặc chạy tay:

```
odoo -u hlv_vtracking -d <database> --stop-after-init
```

Cài xong sẽ tự có: 5 cụm tuyến (Nhơn Trạch, Long Thành – Bình Sơn, Mỹ Xuân – Phú Mỹ – Gò
Dầu, Châu Đức – Vũng Tàu, Hồ Chí Minh) với định mức khởi điểm, các loại địa điểm, 8 tác vụ
nền, và các nhóm quyền.

**Để chi:** định mức khởi điểm là con số phỏng đoán, dùng tạm cho tới khi có dữ liệu thật
(bước 8). Đừng tin nó để hứa giờ với khách.

---

## 2. Cấu hình công ty

**V-Tracking → Cấu hình → Kết nối vTracking**, mở pháp nhân sở hữu kho Bến Cam:

| Ô | Điền | Để chi |
|---|---|---|
| URL vTracking, Khoá API, Timeout | Theo tài khoản nhà cung cấp | Không có thì bản đồ đội xe rỗng, nhưng phần kế hoạch vẫn chạy |
| Nhà cung cấp tra toạ độ | **Google Maps** | OpenStreetMap tra tên khu công nghiệp rất tệ; Google đọc được "KCN Nhơn Trạch 2" |
| Khoá API Google Maps | Khoá từ Google Cloud | Áp dụng **toàn hệ thống** (ghi vào `base_geolocalize.google_map_api_key`), không riêng công ty |
| Bán kính nhận cụm | 3 km (mặc định) | Đo trên 86 ghim: 3 km cho 100% đúng phần tự gán, nới 5 km tụt còn 96% |
| Lấy lộ trình đường thật | **Tắt** lúc đầu | Bật là gọi Google Routes theo lượt, có tính tiền. Chỉ bật khi đã bật Routes API cho khoá |
| Tài khoản worker AI | Để trống, trừ khi làm bước 9 | |

**Để chi:** tra toạ độ là thứ duy nhất biến địa chỉ trên phiếu thành cụm tuyến. Khoá sai
thì mọi phiếu đều "chưa xác định cụm" và kế hoạch chạy trên định mức mặc định.

---

## 3. Nhập 86 điểm giao từ bản đồ

**V-Tracking → Địa điểm → Nhập dữ liệu → Nhập điểm từ bản đồ**, chọn `map2.json`.

Wizard đọc tên lớp trên bản đồ (`"f": "Tuyến Nhơn Trạch"`) để suy cụm, và lấy luôn toạ độ
người ghim sẵn. Xem trước rồi mới ghi.

**Để chi:** toạ độ trong file này do người ghim tay và đã dùng chạy tuyến thật nhiều tháng
— đáng tin hơn kết quả máy tra, nên chúng được lưu ở dạng máy không đè lên. Đây cũng là bộ
điểm mẫu để module suy cụm cho mọi địa chỉ khác: một địa chỉ mới nằm trong 3 km quanh một
ghim thì nhận luôn cụm của ghim đó. Không có bước này thì không có gì để so, và **mọi thứ
phía sau chạy trên dữ liệu rỗng**.

---

## 4. Khai kho và xe

**Kho** — V-Tracking → Địa điểm, tạo (hoặc sửa) điểm loại **Kho**:

- `warehouse_id` trỏ tới kho trong Odoo — **bắt buộc**. Đây là mối nối duy nhất giữa kho
  Odoo và toạ độ trên bản đồ.
- Phải có toạ độ.

**Để chi:** để trống thì kế hoạch xuất phát từ kho đó không tính được chặng kho → điểm đầu
và chặng về, và AI thấy `start_place_id = null` nên không xếp được.

**Xe** — V-Tracking → Đội xe → Xe theo dõi:

- Bật cờ **Theo dõi vTracking** cho đúng những xe của pháp nhân này. Đây là thứ duy nhất
  quyết định module nhìn thấy xe nào — tài khoản vTracking có thể chứa xe của pháp nhân
  khác.
- Khai **điểm xuất phát** của từng xe, và sức chở nếu có.

---

## 5. Tạo điểm cho khách giao nhiều

86 ghim không phủ hết khách. Khách chưa có điểm thì phiếu của họ không có cụm, không treo
được thói quen, và không đóng góp gì cho việc học định mức.

**Cách làm:** V-Tracking → Địa điểm → Nhập dữ liệu → **Tạo địa điểm từ đối tác**, chọn các
pháp nhân, bật "Tra toạ độ ngay".

Chọn ai: lấy danh sách khách nhiều phiếu xuất nhất mà chưa có điểm. Trên staging, 25 khách
đầu chiếm 25% số phiếu chưa gắn được điểm — làm 20–25 khách là đủ để bắt đầu, phần đuôi để
tác vụ nền tra dần.

**Bỏ qua** nhóm bán lẻ / web / Zalo / khách ghé quầy: mỗi phiếu một địa chỉ khác nhau, tạo
điểm cho họ là tạo rác.

### 5b. Mã khách phụ — bước dễ bỏ sót nhất

Cùng một công ty thường nằm ở **nhiều mã khách gốc** khác nhau trong Odoo. Đo trên dữ liệu
thật 22/09/2026: Summit Polymers là #132 và #21366, Dongjin là #133 và #18188, Chosun là
#611 và #1058. Điểm gắn một mã thì phiếu ghi mã kia coi như khách chưa có điểm.

Mở địa điểm, điền ô **"Mã khách khác cùng điểm"** các mã còn lại. Trên staging, riêng bước
này kéo thêm **835 phiếu** vào diện gắn được cụm.

Nếu lỡ tạo hai điểm cho cùng một công ty: **Địa điểm → Dò trùng → Gộp**. Lệnh gộp tự chuyển
mã khách của bản bị gộp thành mã phụ của bản giữ, nên không mất mã nào.

**Cẩn thận:** tên giống nhau chưa chắc là trùng. Dongjin có **hai nhà máy thật** (KCN Dệt
May Nhơn Trạch và KCN Long Bình, cách nhau 28 km) — gộp lại là mất một điểm giao. Xem
khoảng cách giữa hai điểm trước khi gộp.

---

## 6. Nhập luật khách

**V-Tracking → Địa điểm → Nhập dữ liệu → Nhập luật khách từ file**, chọn `khach.json`.

Wizard khớp tên khách với điểm đã có, hiện bảng xem trước, rồi mới ghi. Ba nhóm kết quả cần
xử lý tay:

- **Khớp rõ** — duyệt, ghi.
- **Mơ hồ** (nhiều điểm cùng khớp, ví dụ Hyosung, Posco) — chọn đúng điểm rồi mới ghi.
- **Chưa có điểm** — làm bước 5 cho khách đó trước, rồi chạy lại wizard.

Chạy lại nhiều lần được: wizard nối thêm ghi chú chứ không đè lên thứ người đã sửa.

**Để chi:** file này chứa luật cứng — khách nào cần **thông quan**, khách nào phải **đăng ký
trước**, giờ nhận hàng, cách trả tiền, khách nào phải **ghé cuối tuyến**. Khách cần thông
quan mà mất cờ là xe tới cổng rồi phải chở hàng về. Đây là thứ đắt nhất trong cả gói dữ
liệu: nó là kinh nghiệm nhiều năm của người điều phối, không suy lại được từ số liệu.

---

## 7. Mồi thói quen đã biết

**V-Tracking → Địa điểm → Nhập dữ liệu → Mồi thói quen đã biết**.

Điền thói quen đã biết sẵn trong module vào các điểm đang có, khớp theo tên. Chỉ điền vào ô
còn trống, không đè lên thứ người đã sửa, nên bấm lại nhiều lần vô hại.

Chạy **sau** bước 3 và 5 (phải có điểm rồi mới treo được thói quen vào), và **trước hoặc
sau** bước 6 đều được.

---

## 8. Bật vòng học định mức

Kiểm **Cài đặt → Kỹ thuật → Tác vụ nền**, 8 tác vụ của V-Tracking phải **bật**:

| Tác vụ | Làm gì | Hậu quả nếu tắt |
|---|---|---|
| Cập nhật vị trí đội xe | Kéo vị trí xe | Bản đồ đứng hình |
| Kéo hành trình ngày hôm trước | Lưu vết chạy | Không xem lại được lộ trình |
| Tra toạ độ địa điểm mới | Tra dần phần đuôi | Điểm mới mãi không có toạ độ |
| Đọc số thực tế của kế hoạch | Ghi giờ giao thật vào kế hoạch | Không có gì để đối chiếu |
| Đề xuất định mức cụm từ thực tế | Học định mức | Định mức đứng yên ở số phỏng đoán |
| Gọi lại AI cho yêu cầu còn chờ | Lưới an toàn cho yêu cầu của sale | Yêu cầu nằm chờ mãi |
| Lấy lộ trình đường thật | Chỉ chạy khi đã bật ở bước 2 | — |
| Dọn bản tin vị trí quá hạn | Xoá vết cũ quá hạn lưu trữ | Bảng vị trí phình to |

Sau đó vào **Cụm tuyến & định mức → Tính lại ngay**. Máy dựng lại chuyến từ **nhật ký quét
mã vạch** 180 ngày gần nhất (không cần chờ kế hoạch tích luỹ), đo rồi ghi vào ô *đề xuất*.

Xem số mẫu trước khi bấm **Áp dụng** — cụm dưới chục mẫu thì con số chưa đáng tin. Mỗi lần
áp dụng đều ghi vào Nhật ký hiệu chỉnh, lùi lại được.

**Để chi:** định mức khởi điểm lệch khá xa thực tế. Đo trên staging: chặng điểm → điểm ở
Nhơn Trạch khai 13 phút trong khi thực tế 19 (553 mẫu), Long Thành khai 13 trong khi thực
tế 35 (80 mẫu). Kế hoạch càng nhiều điểm thì càng lệch, và lệch theo hướng hứa sớm hơn khả
năng.

Chặng **về kho** sẽ không có mẫu nào cho tới khi chạy kế hoạch thật — nhật ký quét không
ghi lúc xe về tới kho.

---

## 9. Tuỳ chọn: API cho AI và trang cho sale

### Khoá API

**V-Tracking → Cấu hình → Khoá API → Tạo**. Tắt "Cho phép ghi" trong vài ngày đầu.

Trên máy người dùng:

```bash
export VTRACKING_BASE_URL="https://<instance>.odoo.com"
export VTRACKING_API_KEY="<khoá vừa tạo>"
```

Khoá **không bao giờ nằm trong repo**.

### Trang cho sale — `/giao-hang`

Chạy được ngay, không cần cấu hình. Yêu cầu duy nhất: người dùng có tài khoản Odoo (`auth=
'user'`). Sale không cần quyền trên model kế hoạch — dữ liệu được dựng sẵn ở server.

Nút "Đơn của tôi" lọc theo `x_studio_misa_saler_code` chứ không theo tài khoản Odoo, vì
nhiều nhân viên sale dùng chung một tài khoản.

### Worker AI

Chỉ cần khi muốn sale bấm "nhờ AI xếp lịch" và được trả lời tự động. Xem
`.claude/skills/xu-ly-yeu-cau-dieu-phoi/references/worker-setup.md`. Tóm tắt:

- Tạo một **tài khoản Odoo riêng** cho worker (đừng dùng tài khoản của người — mật khẩu
  lưu trên máy chạy worker), khai vào ô *Tài khoản worker AI* ở bước 2.
- Đặt `VTRACKING_DB`, `VTRACKING_WORKER_LOGIN`, `VTRACKING_WORKER_PASSWORD` trên máy chạy.
- Chạy `ai_worker.py`, nên đăng ký Task Scheduler chạy khi đăng nhập để nó sống lại sau
  khi khởi động máy.

Không chạy worker thì yêu cầu của sale vẫn vào hàng đợi, người điều phối mở ra xử lý tay.

---

## 10. Nghiệm thu

Chạy qua danh sách này trước khi bàn giao:

- [ ] Địa điểm: ≥ 86 điểm, cụm đã gán, có toạ độ. Lọc `no_zone=1` chỉ còn kho và điểm
      ngoài vùng.
- [ ] Kho: điểm loại Kho có `warehouse_id` và toạ độ.
- [ ] Xe: cờ theo dõi bật đúng xe, có điểm xuất phát.
- [ ] Thói quen: khách cần thông quan / đăng ký trước đã có cờ (soi vài khách trong
      `khach.json` xem đúng chưa).
- [ ] Tác vụ nền: 8 tác vụ bật.
- [ ] Lập thử một kế hoạch nháp: km và giờ ra số hợp lý, `missing_coords_count` = 0.
- [ ] Trang `/giao-hang` mở được bằng tài khoản một nhân viên sale thật.

---

## Những gì KHÔNG mang từ staging sang được

| Thứ | Vì sao | Làm lại thế nào |
|---|---|---|
| Toạ độ đã tra | Nằm trong DB staging | Chạy lại bước 3 (file có sẵn toạ độ, miễn phí) + bước 5 (tra mới, vài nghìn đồng cho ~20 khách) |
| Điểm tạo tay, mã khách phụ | Nằm trong DB staging | Làm lại bước 5, hoặc chép sang bằng API nếu số lượng lớn |
| Định mức đã áp dụng | Nằm trong DB staging | Bước 8 — máy học lại từ nhật ký quét của chính production, chính xác hơn |
| Kế hoạch thử nghiệm | Không nên mang | Bỏ |

Đổi lại, **luật khách và điểm trên bản đồ thì mang sang được trọn vẹn** vì chúng nằm trong
file. Đó là lý do hai file ở mục 0 phải được giữ cẩn thận: chúng là phần dữ liệu duy nhất
không dựng lại được từ Odoo.

---

## Bẫy đã mắc phải thật

1. **Push mà không đổi số phiên bản** → server chạy code mới trên cơ sở dữ liệu cũ, lỗi 500
   ở đúng những chỗ dùng field mới.
2. **Gắn khách với điểm theo mã khách** → một công ty có nhiều mã gốc, 50% lần giao không
   gắn được cụm. Dùng ô mã khách phụ (bước 5b).
3. **Suy cụm theo khách thay vì theo địa chỉ** → khách có hai nhà máy ở hai cụm thì một
   nửa số phiếu sai cụm, và định mức học từ đó là định mức của cụm khác.
4. **Tin định mức khởi điểm** → hứa sớm hơn khả năng ở mọi chuyến nhiều điểm.
5. **Gộp điểm chỉ vì trùng tên** → mất một nhà máy thật. Xem khoảng cách trước.
6. **Bật lộ trình đường thật ngay từ đầu** → hoá đơn Google bất ngờ.
