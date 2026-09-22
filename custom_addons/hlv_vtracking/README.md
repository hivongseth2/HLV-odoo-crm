# V-Tracking (`hlv_vtracking`)

Theo dõi định vị đội xe qua **vTracking 2.0 Open API** (bản tài liệu 1.0.3).

Phụ thuộc: `fleet` (Đội xe), `base_geolocalize` (chỉ dùng service `base.geocoder`),
`hlv_geo_utils` (addon thuần hàm). **Không** dính tới điều phối giao hàng.

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
3. Khai xe, theo một trong hai cách:
   - **V-Tracking > Nhập xe từ vTracking** — tạo xe thẳng từ danh sách trên tài khoản
     vTracking. Nhanh nhất khi Đội xe còn trống. Xem mục *Nhập xe* bên dưới.
   - **V-Tracking > Xe theo dõi** — nếu xe đã khai sẵn trong Đội xe: bỏ bộ lọc "Đang theo
     dõi" để thấy cả đội, rồi bật cột **Theo dõi vTracking** cho xe cần giám sát.
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

### Nếu báo HTTP 403

Gần như luôn là **API key sai** — hay gặp nhất là key bị cắt mất đuôi khi sao chép.

Đừng suy ra "bị proxy chặn IP" chỉ vì thân phản hồi là trang HTML của nginx: backend trả
403 với thân rỗng và nginx thay bằng trang lỗi mặc định của nó, nên nhìn thân phản hồi
không biết được ai từ chối.

Phép thử phân biệt: gọi một path bịa đặt.

```bash
curl -sS -k -o /dev/null -w 'HTTP %{http_code}\n' 'https://171.229.16.202:8443/khong-ton-tai'
```

- Ra mã **khác 403** (đo được 503 ngày 17/09/2026) → proxy không chặn IP, vấn đề là key.
- Ra **403** y như request thật → lúc đó mới là bị chặn ở lớp proxy, đi hỏi whitelist IP.

---

## Nhập xe từ vTracking

**V-Tracking > Nhập xe từ vTracking.** Màn hình gọi vTracking lấy toàn bộ xe của tài
khoản, rồi cho biết xe nào Odoo đã có, xe nào chưa. Tick xe muốn tạo và bấm **Tạo xe đã
chọn**.

### Chống trùng

Đối chiếu bằng **biển số đã chuẩn hoá** (bỏ hết ký tự không phải chữ/số, viết hoa), không
bằng chuỗi thô. `60D-00750`, `60D00750`, `60d 00750`, `60D.00750` đều ra cùng một khoá
`60D00750` nên được coi là một xe.

Kiểm ở ba chỗ, vì mỗi chỗ bắt một kiểu trùng khác nhau:

| Chỗ kiểm | Bắt được gì |
|---|---|
| Lúc dựng danh sách | Xe đã có trong Đội xe — dòng bị khoá, không tick được |
| Ngay trước khi ghi | Xe do **người khác vừa tạo** trong lúc màn hình đang mở |
| Trong vòng lặp tạo | Hai dòng cùng biển số trong chính phản hồi của vTracking |

Xe đang nằm trong **lưu trữ** (archived) cũng tính là đã có: tạo thêm một chiếc nữa rồi
mới phát hiện bản cũ trong thùng lưu trữ còn tệ hơn là không tạo được.

### Dòng xe

`fleet.vehicle.model_id` là bắt buộc trong Odoo. Chọn dòng xe ở đầu màn hình để áp cho mọi
xe tạo mới; để trống thì module dùng dòng **"Chưa rõ / Chưa phân loại"** (tự tạo lần đầu)
để luồng không bế tắc khi Đội xe chưa khai dòng xe nào. Sửa lại trên từng xe sau cũng được.

Tạo xong, module gọi đồng bộ một lượt để điền vị trí ngay — trừ khi bạn tắt **Bật theo dõi
cho xe tạo mới**.

## Kế hoạch giao hàng

Đơn vị kế hoạch là **(xe · buổi · ngày)** — ví dụ *60D-00750 · Sáng · 17/09/2026*. Kế
hoạch cả ngày là một buổi đặc biệt (`Cả ngày`), không phải một cấp riêng, để không phải
hỏi "kế hoạch ngày và kế hoạch buổi cái nào đè cái nào".

Đơn vị xếp lên xe là **phiếu giao** (`stock.picking`).

### Xếp lên xe

Ba đường vào, đều mở cùng một hộp thoại và **chọn được nhiều chứng từ một lần**:

- Danh sách **phiếu giao** → Thao tác > *Xếp lên xe (V-Tracking)*
- Danh sách **đơn bán** → Thao tác > *Xếp lên xe (V-Tracking)*
- Trong kế hoạch → nút **Thêm phiếu / đơn**

Chọn kế hoạch có sẵn, hoặc khai luôn (xe, ngày, buổi) để tạo mới tại chỗ.

Chỉ hiện phiếu **xuất kho** đang **Sẵn sàng** và **chưa xếp xe** — phiếu nội bộ, phiếu
Huỷ/Hoàn tất không lọt vào. Sắp xếp ngày giao mới nhất trước.

**Lọc theo kho xuất phát:** nếu địa điểm xuất phát của kế hoạch có gắn kho Odoo
(`hlv.vtracking.place.warehouse_id`), hộp thoại mặc định chỉ hiện chứng từ của đúng kho
đó — xe đang đứng ở kho này thì không lấy được hàng ở kho khác. Bỏ tick *Chỉ lấy chứng từ
của kho đó* khi thực sự gom hàng hai kho.

Một phiếu (và một đơn) chỉ nằm trong **một** kế hoạch — ràng buộc ở CSDL. Chứng từ đã có
kế hoạch thì bị bỏ qua chứ không tự chuyển xe: đổi xe là quyết định của người điều phối,
không phải hệ quả phụ của một lần xếp hàng loạt.

### Xếp đơn khi kho chưa soạn hàng

Điều phối chốt "chiều nay giao đơn này" từ sáng, lúc kho chưa soạn nên **phiếu xuất chưa
tồn tại**. Bắt phải có phiếu mới xếp được thì kế hoạch buổi chiều không lập được vào buổi
sáng — đúng lúc cần lập nhất.

Vì vậy dòng kế hoạch trỏ tới **phiếu giao** *hoặc* **đơn bán**:

| Tình trạng dòng | Nghĩa là |
|---|---|
| **Chờ phiếu xuất** | Mới có đơn bán. Địa chỉ và tiền lấy tạm từ đơn |
| **Đã có phiếu** | Phiếu xuất đã gắn. Địa chỉ và tiền lấy theo phiếu |

Khi kho tạo phiếu xuất cho đơn đó, hệ thống **tự gắn** phiếu vào dòng đang chờ và cập
nhật lại địa chỉ, tiền — không ai phải nhớ quay lại sửa kế hoạch. Chỉ nhận phiếu **xuất**;
phiếu lấy hàng và phiếu đóng gói của cùng đơn không bị gắn nhầm.

Nếu bước tự gắn trượt (lỗi dữ liệu chẳng hạn), việc tạo phiếu của kho **không** bị hỏng —
dòng vẫn ở *Chờ phiếu xuất* và gắn tay được.

### In kế hoạch

Nút **In** trên kế hoạch. Đầu tờ là bốn con số tài xế cần (số phiếu · tiền · km · thời
gian), rồi bảng theo thứ tự ghé với ô ☐ để tích tay, cuối là hai ô ký. Điểm chưa có toạ độ
được đánh dấu ngay trên tờ in vì km ở đầu tờ chưa tính phần của chúng.

### Tra toạ độ và kho toạ độ dùng lại

Địa chỉ lấy từ ô **Địa chỉ giao hàng** trên phiếu (`x_studio_a_ch_giao_hng`); không có thì
lùi về địa chỉ liên hệ của khách. Tiền lấy thẳng ô **Tổng tiền sau thuế**
(`x_studio_ng_tin_sau_thu`) — không tự cộng lại từ dòng hàng, vì đó là con số kho và kế
toán đang nhìn.

Cả hai đọc qua `_fields` nên module vẫn cài được ở nơi chưa tạo các field Studio đó.

**Tra nội bộ trước, không có mới gọi ra ngoài.** Mọi lượt tra đi qua
`hlv.vtracking.address.resolve()` — đường vào duy nhất:

1. Chuẩn hoá địa chỉ thành khoá: bỏ dấu, mở viết tắt (`P.5` → `phuong 5`, `Q.1` → `quan 1`,
   `KCN` → `khu cong nghiep`, `TP.HCM` → `ho chi minh`), bỏ hết ký tự không phải chữ/số.
2. Tìm khoá đó trong **V-Tracking > Địa điểm > Kho toạ độ**. Có thì dùng luôn, tăng đếm
   *Dùng lại*.
3. Không có mới gọi geocoder, rồi lưu lại cho lần sau.

Nhờ chuẩn hoá, ba cách viết này ra cùng một khoá và chỉ tốn **một** lượt gọi:

```
260/49 Nguyễn Thái Sơn, P.5, Gò Vấp, TP.HCM
260/49 nguyen thai son, phuong 5, go vap, tphcm
260/49  Nguyễn Thái Sơn , P5 , Gò Vấp , TP HCM
```

### Chuỗi gửi đi tra ≠ địa chỉ gốc

Ô **Địa chỉ gốc** giữ nguyên văn để đối chiếu. Ô **Địa chỉ đã chuẩn hoá** mới là chuỗi
thật sự gửi đi, và nó được cắt gọn:

| Bỏ đi | Vì sao |
|---|---|
| Cụm tên công ty ở đầu | Odoo ghép tên khách vào `contact_address`; gửi tên đi làm Nominatim đi tìm doanh nghiệp cùng tên ở nơi khác |
| Cụm rỗng (`, ,`) | Rác từ ô street2 bỏ trống |
| Cụm trùng, cụm nằm trong cụm khác | Người nhập đã gõ đủ tỉnh/huyện vào street, Odoo lại ghép thêm city/state/country |

Ví dụ thật, từ 118 ký tự còn 34:

```
CÔNG TY TRÁCH NHIỆM HỮU HẠN DONGJIN TEXTILE VINA, Huyện Nhơn Trạch,
Đồng Nai, Việt Nam, , Đồng Nai, Đồng Nai Việt Nam
        ↓
huyen nhon trach, dong nai viet nam
```

Ngoại lệ: khi nhà cung cấp là **Google**, cụm tên công ty được **giữ lại** — Google tra
được cả tên doanh nghiệp. Đổi nhà cung cấp rồi bấm *Tra lại* thì chuỗi được tính lại cho
khớp.

### Toạ độ ngoài Việt Nam bị từ chối

Kết quả geocode rơi ngoài khung Việt Nam (vĩ độ 8–23.6, kinh độ 102–110) **không được
lưu** — ghi rõ toạ độ sai là bao nhiêu và cách xử lý. Một điểm sai kiểu đó đủ làm quãng
đường cả kế hoạch nhảy lên hàng nghìn km mà không ai biết vì sao.

Dữ liệu sai đã lưu từ trước: lọc bằng *Toạ độ ngoài Việt Nam* trong **Địa điểm > Kho toạ
độ**, sửa địa chỉ hoặc dán toạ độ tay, rồi bấm **Đọc lại từ chứng từ** trên kế hoạch.

Cột **Dùng lại** cho thấy cache tiết kiệm được bao nhiêu lượt. Bản ghi `failed` không tự
tra lại: máy đã trượt với đúng chuỗi đó thì lần sau cũng trượt — bấm nút *Tra lại* hoặc
dán toạ độ tay.

### Quãng đường và thời gian

| Con số | Cách tính |
|---|---|
| Quãng đường | Đường chim bay nối các điểm theo thứ tự ghé (kể cả điểm xuất phát), **nhân hệ số đường bộ** |
| Thời gian chạy | Quãng đường ÷ tốc độ trung bình |
| Thời gian giao | Số phiếu × phút mỗi điểm |
| Tổng | Chạy + giao, hiện dạng `2h15'` |

Ba tham số khai ở **Cấu hình > Kết nối vTracking**, mục *Định mức tính kế hoạch*: tốc độ
trung bình (mặc định 35 km/h), phút mỗi điểm (10), hệ số đường bộ (1.3).

Mặc định **không gọi Google**: gọi API mỗi lần đổi thứ tự điểm là trả tiền cho một con số
chỉ dùng để so các phương án với nhau. Khi có km GPS thực tế thì chỉnh hệ số cho khớp địa
bàn — đó là cách làm nó chính xác dần.

Cần km đúng theo đường bộ thì bật thêm lộ trình đường thật, xem mục dưới. Con số chim bay
vẫn giữ nguyên chứ không bị thay thế: nó là thứ **so được giữa mọi chuyến**, kể cả chuyến
chưa lấy hoặc không lấy được đường thật.

Phiếu chưa có toạ độ **không** vào được quãng đường; ô *Điểm thiếu toạ độ* và cảnh báo
trên form nói rõ con số đang thiếu phần nào. Nút **Sắp thứ tự theo điểm gần nhất** cho
một thứ tự khởi đầu đỡ tệ hơn thứ tự nhập tay (không phải lời giải tối ưu), phiếu thiếu
toạ độ dồn xuống cuối.

### Kế hoạch ≠ thực tế

Kế hoạch là **bản dự thảo**. Tab *Thực tế* lấy số từ `hlv_barcode_shipper` (lúc shipper
quét nhận hàng, lúc phiếu giao xong, hàng chở về) và từ lịch sử GPS của xe. Cron đọc lại
mỗi giờ cho kế hoạch **đã chốt / xong** trong 2 ngày gần nhất; kế hoạch nháp chưa ai chạy
nên không đọc.

Đừng suy số thực tế từ kế hoạch: hai nguồn khác nhau, trộn vào là mất khả năng đối chiếu.

### Hiệu chỉnh định mức

Menu **Giao hàng > Hiệu chỉnh định mức** — theo dõi vòng tự học:

- **Độ chính xác dự báo** — mỗi điểm đã giao: dự kiến tới lúc nào, thực tế tới lúc nào.
  Pivot theo cụm × tuần: *Đúng hẹn (%)* (lệch ≤ 15 phút) và *Lệch tuyệt đối* (phút). Chỉ
  gồm điểm **đo được** — đã giao mà thiếu toạ độ hay thiếu mốc xuất phát thì không có mặt,
  vì lệch "0" của chúng là không biết chứ không phải đúng giờ (`variance_measured`).
- **Nhật ký hiệu chỉnh** — mỗi tối cron đo lại trung vị từng định mức của từng cụm, ghi một
  dòng (định mức lúc đó, đo được, đề xuất, số mẫu). Mỗi lần bấm *Áp dụng* cũng ghi một dòng:
  cũ → mới, ai bấm. Dạng biểu đồ cho thấy định mức từng cụm trôi theo tuần.
- **Cụm tuyến & định mức** — chuyển từ Cấu hình sang đây: cột *→ đề xuất* và nút *Áp dụng*.

Máy **chỉ đề xuất**, không tự sửa định mức: cần ≥ 10 mẫu và lệch ≥ 2 phút mới có đề xuất.

### Trên bản đồ

Bấm vào xe, popup hiện **kế hoạch hôm nay** của xe đó (mọi buổi): số phiếu, tiền, km và
thời gian dự kiến, danh sách điểm giao theo thứ tự ghé — kèm dòng *Thực tế* lấy từ mốc shipper quét — chưa ai quét thì ghi rõ là chưa có, để
không ai nhầm số dự kiến thành số đã giao.

Mỗi kế hoạch có hai nút: **Xem bảng** (hộp thoại đầy đủ) và **Lộ trình**.

#### Lộ trình dự kiến

Bấm **Lộ trình** vẽ đường đi lên bản đồ: điểm xuất phát (kho, ghim đỏ) → từng điểm giao
theo thứ tự ghé, mỗi điểm một ghim tròn tím đánh số. Số trên bản đồ **khớp với số trên tờ
kế hoạch in ra**, kể cả khi có điểm bị bỏ qua vì thiếu toạ độ.

Kiểu đường vẽ chính là thông tin:

| Kiểu | Nghĩa |
|---|---|
| **Nét đứt** | Đường nối thẳng giữa các điểm — **không phải đường đi thật**. Nét liền sẽ khiến người xem tin rằng xe chạy đúng theo vệt đó. |
| **Nét liền** | Đường đi thật lấy từ Google Routes, vẽ theo đúng đường xe chạy |

#### Lộ trình đường thật (Google Routes)

Tắt sẵn. Bật ở **Cấu hình > Kết nối vTracking**, mục *Lộ trình đường thật*. Dùng **chung
khoá** với phần tra toạ độ (`base_geolocalize.google_map_api_key`) — cùng lý do như ở đó:
hai chỗ giữ hai khoá là kiểu lỗi mà người dùng đổi một chỗ rồi không hiểu sao chỗ kia vẫn
hỏng. Khoá đó phải được bật thêm **Routes API** trong Google Cloud Console, không chỉ
Geocoding API; chưa bật thì mỗi chuyến chỉ ghi lại một dòng lỗi đọc được trên form.

Lấy về thì **lưu lại** trên kế hoạch (`road_polyline`, `road_distance_km`,
`road_duration_minutes`), không gọi lại mỗi lần vẽ: bản đồ tự tải lại mỗi 30 giây, gọi API
trong đường đọc đó vừa đốt hạn mức cho thứ không đổi, vừa cộng thời gian chờ mạng vào một
endpoint người dùng đang ngồi trước.

Khi nào gọi API:

- **Cron 10 phút** lấy cho chuyến từ hôm nay trở đi còn thiếu đường vẽ, tối đa 20 chuyến
  mỗi lượt. Chuyến **đã từng lỗi** thì cron KHÔNG tự gọi lại — phải xử lý nguyên nhân rồi
  bấm lấy lại, để một chuyến có toạ độ sai không gọi API mỗi 10 phút suốt ngày.
- **Nút "Lấy lộ trình đường thật"** trên form kế hoạch: bấm là gọi ngay, kể cả khi đã có
  đường cũ.

Thứ tự ghé đổi sau khi lấy thì đường đã lưu là của thứ tự **cũ**: form hiện cảnh báo và
bản đồ **quay về nét đứt** — thà vẽ thô mà đúng thứ tự hiện tại còn hơn vẽ đẹp một lộ
trình không còn tồn tại. Không tự gọi lại ở đây vì người điều phối còn đang kéo thả sắp
xếp, gọi mỗi lượt kéo là đốt hạn mức.

Phạm vi lộ trình là **kho → điểm cuối, không gồm chặng về kho**, giống hệt ô *Quãng đường
(km)* — để hai con số so được với nhau. Chặng về chỉ tính vào thời gian.

Giới hạn: tối đa 23 điểm giữa mỗi lượt gọi. Vượt thì **báo lỗi**, không lặng lẽ cắt bớt
điểm (cắt là vẽ ra lộ trình thiếu điểm mà người xem không biết). Chuyến thực tế 8-12 điểm
nên gần như không chạm tới.

Thời gian Google trả về (`road_duration_minutes`) chỉ là thời gian **chạy thuần** và
KHÔNG thay thế ô *Dự kiến*: ô đó dùng định mức đo từ chuyến thật, gồm cả bốc dỡ và ký
nhận tại điểm, sát hơn với cách đội xe chạy. Cố tình gọi bản **không có traffic**
(`TRAFFIC_UNAWARE`): con số được lưu lại và đem so giữa các chuyến nên phải ổn định, còn
muốn giờ sát thực tế thì định mức cụm tốt hơn.

Thanh thông tin hiện trên đầu bản đồ với mẫu nét đứt (kiêm chú giải), km, thời gian, và
báo rõ khi chỉ vẽ được một phần: *vẽ 6/8 điểm — số còn lại chưa có toạ độ*. Nút **Ẩn** ở
thanh đó, không nằm trong popup, vì lúc muốn tắt thì popup thường đã đóng.

Chọn kế hoạch khác thì lộ trình cũ tự thay; bấm lại đúng kế hoạch đang hiện thì tắt. Lộ
trình được vẽ lại sau mỗi lượt làm tươi 30 giây, nên đổi thứ tự điểm trong Odoo là bản đồ
cập nhật theo.

## Địa điểm trên bản đồ

Ngoài xe, bản đồ hiện các **địa điểm cố định**: kho, đối tác, nhà cung cấp…

### Loại địa điểm

**V-Tracking > Cấu hình > Loại địa điểm.** Loại quyết định ghim hiện thế nào:

| Thuộc tính | Tác dụng |
|---|---|
| Màu | Màu ghim |
| Cỡ | Nhỏ / Vừa / **Lớn — nổi bật** |
| Luôn hiện tên | Hiện tên cạnh ghim không cần rê chuột |
| Hiện sẵn | Tắt thì người xem phải tự bật lớp đó lên |

Cài sẵn 5 loại: **Kho** (đỏ, cỡ lớn, luôn hiện tên), Đối tác, Khách hàng, Nhà cung cấp,
Khác (tắt sẵn). Sửa hoặc thêm loại tuỳ ý — đây là dữ liệu của bạn, nâng cấp module không
đè lên.

Cỡ là thuộc tính của **loại**, không của từng điểm: đó là cách để kho nổi bật giữa hàng
trăm ghim đối tác mà không phải chỉnh tay từng cái.

### Tạo địa điểm

- **Tạo tay**: V-Tracking > Địa điểm > Mới.
- **Hàng loạt từ đối tác**: V-Tracking > Tạo địa điểm từ đối tác — chọn nhiều công ty,
  chọn loại, tick "Tra toạ độ ngay". Đối tác đã có địa điểm thì bỏ qua, không tạo trùng.
  Tối đa 200 đối tác một lần.

### Tra toạ độ

Dùng `base.geocoder` của **base_geolocalize** — không tự viết HTTP client. Chọn nhà cung
cấp ở **V-Tracking > Cấu hình > Kết nối vTracking**, mục *Tra toạ độ địa điểm*:

- **OpenStreetMap** — miễn phí, 1 lượt/giây.
- **Google Maps** — cần khoá API, tính tiền theo lượt. Tra **tên doanh nghiệp** tốt hơn
  hẳn, nên với địa chỉ khu công nghiệp thì nên dùng Google.

Hai ô đó ghi thẳng vào tham số hệ thống của base_geolocalize
(`base_geolocalize.geo_provider`, `base_geolocalize.google_map_api_key`) nên **áp dụng
toàn hệ thống**, không riêng một công ty. Cố ý làm vậy: hai chỗ cùng giữ một khoá Google
là kiểu lỗi mà người dùng đổi khoá ở chỗ này rồi không hiểu vì sao chỗ kia vẫn hỏng.

Chuỗi gửi đi tra ghép **tên địa điểm + địa chỉ đối tác** (xem ô *Địa chỉ dùng khi tra*),
vì địa chỉ trong Odoo thường chỉ tới cấp phường.

### Máy tra rồi người duyệt

Toạ độ máy tra vào trạng thái **Chờ duyệt**, không dùng ngay. Soát bằng bộ lọc *Chờ duyệt
toạ độ*, bấm **Duyệt toạ độ** khi đúng.

Máy tra trượt thì mở Google Maps, chuột phải vào đúng chỗ, copy cặp số rồi dán vào ô
*Dán toạ độ*. **Toạ độ nhập tay không bao giờ bị máy đè lên** — kể cả khi bấm tra lại
hay khi tác vụ nền chạy.

Tác vụ nền *V-Tracking: tra toạ độ địa điểm mới* chạy mỗi giờ, mỗi lượt 20 điểm, chỉ đụng
điểm **chưa tra**. Bật sẵn vì nó không đụng tài khoản vTracking — nhưng nếu bạn chuyển
sang Google thì cân nhắc lại, Google tính tiền theo lượt.

### Trên bản đồ

Góc phải là bảng chú giải kiêm bộ lọc: bấm vào một loại để bật/tắt lớp đó. Lớp địa điểm
chỉ tải **một lần** lúc mở màn hình — lượt làm tươi 30 giây là để theo dõi xe, vẽ lại
hàng trăm ghim đứng yên mỗi lần là phí.

Trang `/giao-hang` (bản đồ cho người bán hàng) chỉ vẽ **kho**, không vẽ đối tác/khách hàng:
số ghim khách lên tới hàng trăm, vẽ hết là lấp mất xe — mà điểm giao của chuyến đã có ghim
số thứ tự riêng khi xem lộ trình. Kho hiện ngay khi bản đồ mở: không có nó thì một chấm xe
giữa bản đồ không cho biết xe đang đi ra hay đang về. Lọc theo **mã loại**
(`type_id.code = 'warehouse'`) chứ không theo tên, vì tên loại người dùng sửa được.

#### Bản đồ trang `/giao-hang` chỉ dựng khi chọn chuyến

Cột phải mặc định là một ô nhắc *"Bấm một chuyến bên trái…"*, **chưa dựng bản đồ**. Bấm một
thẻ chuyến mới dựng Leaflet, vẽ xe + kho và vẽ lộ trình của đúng chuyến đó; bấm lại thẻ đang
chọn (hoặc nút ✕) thì đóng.

Lý do: chưa chọn chuyến thì bản đồ chỉ là một ô trống chiếm nửa màn hình, mà vẫn tải tile và
vẽ lại mỗi 30 giây. Kéo theo hai luật trong code, đừng phá:

- `VtSaleMap.update()` / `showPlaces()` / `showRoute()` **không tự dựng** bản đồ, chỉ trả về
  ngay khi chưa mở. Chỉ `open()` dựng, và trang chỉ gọi `open()` **sau** khi đã bỏ lớp ẩn —
  Leaflet đo kích thước khung lúc khởi tạo, dựng trên khung đang ẩn thì bản đồ ra méo.
- Lượt làm tươi 120 giây vẽ lại lộ trình với `fit=false`: khớp dữ liệu mới nhưng không kéo
  khung nhìn. Người đang phóng to xem một điểm mà cứ 2 phút bị giật về toàn tuyến thì không
  xem được gì.

Thẻ chuyến ở cột trái cũng gọn lại: xe, buổi, cụm, ba con số, và một **dải điểm cuộn ngang**
(số thứ tự + tên khách + giờ tới). Toàn bộ chi tiết — địa chỉ, chứng từ, nút *Xin đổi lịch* —
nằm ở cột phải. Trước đây mỗi thẻ tự mở sẵn cả danh sách điểm kèm nút, ba chuyến là đã phải
cuộn và không còn nhìn ra chuyến nào là chuyến nào.

### Quan hệ với `hlv.delivery.point`

Module `hlv_delivery_dispatch` đã có model điểm giao hàng riêng, cùng luồng "máy tra →
người duyệt". Hai bên **không dùng chung dữ liệu**, vì V-Tracking cố ý chỉ phụ thuộc
`fleet` + `base_geolocalize`.

Phạm vi khác nhau: `hlv.delivery.point` là điểm giao hàng có cụm tuyến, thói quen khách,
gắn với chuyến; `hlv.vtracking.place` chỉ là địa điểm tham chiếu trên bản đồ. Nếu sau này
cần một nguồn duy nhất thì nối ở module cầu nối, đừng cho module này phụ thuộc điều phối.

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

### `GET /api/v1/fleet/places`

Địa điểm cố định (kho, đối tác…) kèm màu và cỡ của từng loại, để app vẽ giống Odoo.
Tham số: `type` lọc theo mã loại, `confirmed_only=1` chỉ lấy toạ độ đã duyệt hoặc nhập
tay — dùng khi app không muốn hiển thị phỏng đoán của máy.

### `GET /api/v1/fleet/map-config`

Nguồn tile bản đồ, để ứng dụng ngoài vẽ cùng nền bản đồ với Odoo.

---

## API cho AI lập kế hoạch

Bộ endpoint `/api/v1/ai/*` để một AI agent (Claude) đọc tình hình đơn hàng, kho, xe rồi đề
xuất hoặc lập kế hoạch giao hàng. Tài liệu viết cho chính AI đó đọc:

- [docs/AI_API_GUIDE.md](docs/AI_API_GUIDE.md) — quy trình suy nghĩ, luật nghiệp vụ, chỗ dễ hiểu sai.
- [docs/AI_API_REFERENCE.md](docs/AI_API_REFERENCE.md) — tra cứu 19 endpoint.
- [`.claude/skills/dieu-phoi-giao-hang/`](../../.claude/skills/dieu-phoi-giao-hang/) —
  skill điều phối cho Claude Code: quy trình, bẫy đã mắc, và lớp gọi API. Mở Claude Code
  trong repo là dùng được; chỉ cần tạo khoá API theo `references/setup.md`.

Cấp khoá ở **Cấu hình > Khoá API**. Khoá mặc định **chỉ đọc**; bật **Cho phép ghi** thì mới
tạo/sửa kế hoạch được. Mọi thao tác ghi qua API để lại một dòng trên chatter của kế hoạch,
ghi tên khoá đã làm.

Code: `controllers/ai/` (endpoint mỏng) → `services/ai/` (nghiệp vụ) → `tools/` (hàm thuần).
Luật xếp chứng từ (`services/plan_documents.py`) và phép tính lộ trình
(`tools/vtracking_route.py`) dùng **chung** giữa giao diện người dùng và API — AI không
thấy một tập phiếu khác, và không ra một con số km khác, so với người điều phối.

## Cấu trúc code

Màn cấu hình là một form của **`res.company`**, không phải `res.config.settings`. Lý do:
action của `res.config.settings` luôn được Odoo mở trong app Cài đặt và **thay chỗ trang
Cài đặt chung** — bấm menu của module này lại làm mất màn hình cài đặt gốc.

| Thư mục | Được làm gì | Không được làm gì |
|---|---|---|
| `tools/` | Hàm thuần: chuẩn hoá biển số, đổi thời gian, bóc payload | Không `env`, không mạng, không side effect |
| `services/vtracking_client.py` | Nói HTTP với vTracking, phân trang, lùi dần khi 429 | Không biết Odoo là gì |
| `services/google_routes.py` | Nói HTTP với Google Routes, đổi lỗi thành câu đọc được | Không dựng body, không đọc số — phần đó ở `tools/vtracking_road_route.py` để test được |
| `services/vtracking_sync.py` | Nối hai lớp trên, ghi vào Odoo | — |
| `models/`, `controllers/` | Mô hình dữ liệu, giao diện, API | Không chứa hàm dùng chung |

Ranh giới này để: gọi thử client từ shell mà không cần dựng env, và test thuật toán trong
`tools/` mà không cần Odoo.

Hàm dùng chung toàn hệ thống (đọc chuỗi toạ độ dán tay, đo khoảng cách) lấy từ
**`hlv_geo_utils`**, không viết lại — điều phối giao hàng và đi nhận hàng đã dùng chung nó,
và cùng một chuỗi toạ độ phải cho ra cùng một kết quả ở mọi module. `tools/` của module này
chỉ giữ thứ riêng của vTracking: chuẩn hoá biển số, đổi epoch mili-giây, bóc payload.

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

- Tự học thời gian đứng tại từng khách (`extra_service_minutes`) — hiện mới hiệu chỉnh
  cấp cụm.
- Xem lại hành trình một ngày trên bản đồ (hiện chỉ có danh sách bản tin trong form xe).
- Thông báo khi có cảnh báo lái quá giờ — dữ liệu đã lấy về, chưa đẩy ra ai.
- Lộ trình đường thật chưa tự lấy lại khi đổi thứ tự ghé (cố ý: tránh gọi API mỗi lượt kéo
  thả) — hiện phải bấm nút. Nếu về sau thấy bất tiện thì nên gọi khi **chốt** kế hoạch.
