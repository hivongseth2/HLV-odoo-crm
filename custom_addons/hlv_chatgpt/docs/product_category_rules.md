# QUY TẮC PHÂN NHÓM HÀNG HÓA HLV

Tài liệu tra cứu bắt buộc. Phải đọc tài liệu này trước khi chốt nhóm hàng cho bất kỳ
sản phẩm nào.

---

## 0. HAI ĐIỀU QUAN TRỌNG NHẤT

**1. HÃNG THẮNG CHỨC NĂNG.** Nếu hàng thuộc một hãng có nhóm riêng, luôn xếp vào nhóm
của hãng đó, kể cả khi có một nhóm chức năng nghe hợp lý hơn.

> Ví dụ chuẩn: **Mũi khoan Bosch** xếp vào `PKBOSCH` (Phụ kiện BOSCH), **không** xếp vào
> `MUIKHOANTARO`. Lý do: báo cáo doanh số theo hãng là nhu cầu chính của kho.

`MUIKHOANTARO` chỉ dành cho mũi khoan của hãng **không có nhóm riêng**.

**2. ID trong tài liệu này là để tham khảo, không phải nguồn sự thật.**
Trước khi gọi `create_product_misa`, **bắt buộc** gọi `search_category_misa` với tên
nhóm đã chọn để lấy ID thật từ MISA. Danh sách dưới đây có thể đã cũ nếu kho vừa thêm
hoặc đổi nhóm. Nếu ID từ tool khác ID trong tài liệu, **lấy ID từ tool**.

---

## 1. LỘ TRÌNH PHÂN NHÓM

Chạy từ trên xuống, dừng ở bước đầu tiên có kết quả.

### Bước 1 — Hàng có hãng, và hãng đó có nhóm riêng?

Xem mục 2. Nếu có, chọn nhóm của hãng đó, rồi phân loại tiếp trong nội bộ hãng theo
mục 1.1.

### Bước 2 — Hàng có hãng nhưng hãng không có nhóm riêng?

Ví dụ KINGTONY, ASAKI, TOTAL, STANLEY. Chuyển sang nhóm chức năng ở mục 3.

### Bước 3 — Hàng không có hãng?

Chọn nhóm chức năng ở mục 3 theo bản chất công dụng của hàng.

### Bước 4 — Không xếp được vào đâu?

`DANHMUCKHAC` — ID 2. **Chỉ dùng khi thật sự bất lực.** Phải nói rõ lý do với người
dùng và hỏi họ có gợi ý nhóm nào khác không.

### 1.1 Phân loại trong nội bộ một hãng

Các hãng lớn được chia thành nhiều nhóm con. Chọn theo bản chất của món hàng:

| Nhóm con | Là gì | Ví dụ |
|---|---|---|
| **Máy** | Thiết bị có động cơ, chạy điện hoặc pin | máy khoan, máy cắt, máy mài |
| **Công cụ, dụng cụ** | Dụng cụ cầm tay không động cơ | cờ lê, tuốc nơ vít, kìm, thước |
| **Phụ kiện** | Đồ gắn vào máy để làm việc, hao mòn theo công việc | mũi khoan, lưỡi cắt, đầu vặn, chổi quét |
| **Phụ tùng** | Linh kiện thay thế của chính cái máy | chổi than, bạc đạn, vỏ máy, công tắc |
| **Packout / Quà tặng** | Thùng đựng, hộp, đồ khuyến mãi | thùng Packout, áo, mũ |

> Ranh giới **Phụ kiện** và **Phụ tùng** là chỗ dễ nhầm nhất. Câu hỏi phân biệt: *món
> này gắn vào máy để LÀM VIỆC (phụ kiện) hay để SỬA MÁY (phụ tùng)?* Mũi khoan là phụ
> kiện. Chổi than là phụ tùng.

---

## 2. NHÓM THEO HÃNG

Hàng thuộc các hãng dưới đây **luôn** xếp vào nhóm của hãng, không xếp theo chức năng.

### MILWAUKEE

| Nhóm | Mã | ID |
|---|---|---|
| Máy MILWAUKEE | `MAYMIL` | 166 |
| Công cụ, dụng cụ MILWAUKEE | `CCDCMIL` | 165 |
| Phụ kiện MILWAUKEE | `PKMIL` | 238 |
| Phụ tùng MILWAUKEE | `PTMIL` | 167 |
| Packout MILWAUKEE | `PACKOUTMIL` | 226 |
| Quà tặng MILWAUKEE | `QTMIL` | 227 |

### BOSCH

| Nhóm | Mã | ID |
|---|---|---|
| Máy điện BOSCH | `MAYDIENBOSCH` | 222 |
| Máy pin BOSCH | `MAYPINBOSCH` | 221 |
| Máy đo BOSCH | `MAYDOBOSCH` | 223 |
| Công cụ, dụng cụ BOSCH | `CCDCBOSCH` | 268 |
| Phụ kiện BOSCH | `PKBOSCH` | 224 |
| Phụ tùng BOSCH | `PTBOSCH` | 231 |
| Quà tặng BOSCH | `QTBOSCH` | 228 |

### MAKITA

| Nhóm | Mã | ID |
|---|---|---|
| Máy điện MAKITA | `MAYDIENMAKITA` | 170 |
| Máy pin MAKITA | `MAYPINMAKITA` | 234 |
| Công cụ, dụng cụ MAKITA | `CCDCMAKITA` | 171 |
| Phụ kiện MAKITA | `PKMAKITA` | 169 |
| Phụ tùng MAKITA | `PTMAKITA` | 235 |

### DEWALT

| Nhóm | Mã | ID |
|---|---|---|
| Máy DEWALT | `MAYDEWALT` | 174 |
| Công cụ, dụng cụ DEWALT | `CCDCDEWALT` | 173 |
| Phụ kiện DEWALT | `PKDEWALT` | 175 |

### KARCHER

| Nhóm | Mã | ID |
|---|---|---|
| Công nghiệp KARCHER | `KARCHER-CN` | 246 |
| Dân dụng KARCHER | `KARCHER-DANDUNG` | 245 |
| Hóa chất vệ sinh KARCHER | `KARCHER-HC` | 259 |

### Các hãng chuyên ngành

| Nhóm | Mã | ID |
|---|---|---|
| Vòng bi, gối đỡ và phụ kiện SKF | `VONGBIVAGOIDOSKF` | 184 |
| Mỡ SKF | `MOSKF` | 237 |
| Vòng bi, gối đỡ các hãng Nhật (KOYO, ASAHI, NTN, NSK) | `KOYO, ASAHI, NTN, NSK` | 6 |
| Dây curoa MITSUBOSHI | `MITSUBOSHI` | 17 |
| Dây curoa BANDO | `BANDO` | 43 |
| Vật tư khí nén SMC | `KHINENSMC` | 141 |
| Dụng cụ đo MITUTOYO | `MITUTOYO` | 107 |
| Dụng cụ đo INSIZE | `DUNGCUDOINSIZE` | 134 |
| Tủ đồ nghề CSPS | `CSPS` | 118 |
| Dầu mỡ MOBIL, SHELL | `MOBIL, SHELL` | 202 |

---

## 3. NHÓM THEO CHỨC NĂNG

Dùng khi hãng không có nhóm riêng, hoặc hàng không có hãng.

### Thiết bị điện

| Nhóm | Mã | ID |
|---|---|---|
| Thiết bị điện lắp ngoài | `THIETBIDIENLAPNGOAI` | 11 |
| Thiết bị điện cho tủ điện | `THIETBITUDIEN` | 218 |
| Thiết bị điện chuyên dụng | `THIETBIDIENCHUYENDUNG` | 254 |
| Thiết bị đo điện | `THIETBIDODIEN` | 255 |
| Thiết bị điện mặt trời | `THIETBIDIENMATTROI` | 256 |
| Dây điện | `DAYDIEN` | 39 |

### Truyền động

| Nhóm | Mã | ID |
|---|---|---|
| Dây curoa, băng tải khác | `DAYCUROAKHAC` | 12 |
| Puly, nhông, xích, khớp nối | `PULY,BANHRANG,KHOPNOI` | 16 |
| Sin, phốt | `SINPHOT` | 266 |
| Vòng bi và gối đỡ khác | `VONGBIKHAC` | 188 |

### Dụng cụ cầm tay

Phân theo phân khúc chất lượng:

| Nhóm | Mã | ID |
|---|---|---|
| Dụng cụ cầm tay cao cấp | `DUNGCUCAOCAP` | 251 |
| Dụng cụ cầm tay thương hiệu tầm trung | `DUNGCUTAMTRUNG` | 248 |
| Dụng cụ cầm tay loại thường có thương hiệu | `DUNGCUTHUONG` | 249 |
| Dụng cụ cầm tay không thương hiệu | `DUNGCUGIARE` | 250 |
| Cờ lê lực | `COLELUC` | 252 |

### Dụng cụ đo

| Nhóm | Mã | ID |
|---|---|---|
| Dụng cụ đo khác | `DUNGCUDOKHAC` | 101 |

### Cắt, mài, khoan

| Nhóm | Mã | ID |
|---|---|---|
| Đá cắt, đá mài, nhám xếp | `DAMAICAT` | 210 |
| Lưỡi cắt, cưa | `LUOICAT` | 260 |
| Mũi khoan, mũi taro, mũi phay | `MUIKHOANTARO` | 211 |

### Đường ống

| Nhóm | Mã | ID |
|---|---|---|
| Thiết bị đường ống kim loại | `DUONGONGKIMLOAI` | 208 |
| Thiết bị đường ống nhựa | `DUONGONGNHUA` | 209 |
| Thiết bị đường ống thủy lực | `DUONGONGTHUYLUC` | 253 |

### Khí nén

| Nhóm | Mã | ID |
|---|---|---|
| Vật tư khí nén khác | `VATTUKHINENKHAC` | 53 |

### Bulong, đinh vít

| Nhóm | Mã | ID |
|---|---|---|
| Bulong máy | `BULONGMAY` | 257 |
| Bulong xây dựng | `BULONGXD` | 258 |
| Đinh vít các loại | `DINHVIT` | 192 |

### Nâng hạ

| Nhóm | Mã | ID |
|---|---|---|
| Xe nâng và phụ kiện xe nâng các hãng | `XENANG` | 205 |
| Thiết bị nâng hạ khác | `THIETBINANGKHAC` | 206 |

### Dầu mỡ, hóa chất

| Nhóm | Mã | ID |
|---|---|---|
| Dầu mỡ khác | `MOKHAC` | 204 |
| Keo dán, silicone | `KEODAN` | 264 |
| Sơn và phụ kiện | `SON` | 220 |

### Vật tư khác

| Nhóm | Mã | ID |
|---|---|---|
| Bảo hộ lao động | `BAOHOLAODONG` | 54 |
| Vật tư vệ sinh làm sạch | `VATTUVESINH` | 207 |
| Vật tư đóng gói | `VATTUDONGGOI` | 265 |
| Bánh xe đẩy công nghiệp | `BANHXEDAY` | 261 |
| Bình ắc quy, pin | `ACCQUY` | 262 |
| Nguyên liệu gia công | `NGUYENLIEUGIACONG` | 263 |
| Máy cầm tay Trung Quốc | `MAYCAMTAYTQ` | 247 |
| Máy hàn và phụ kiện hàn khác | `MAYHANKHAC` | 183 |

### Cuối cùng

| Nhóm | Mã | ID |
|---|---|---|
| Danh mục khác | `DANHMUCKHAC` | 2 |

Chỉ dùng khi đã chạy hết bước 1 đến bước 3 mà không xếp được.

---

## 4. VÍ DỤ ÁP DỤNG

| Sản phẩm | Nhóm | Lý do |
|---|---|---|
| Mũi khoan bê tông BOSCH | `PKBOSCH` (224) | Hãng thắng chức năng. Không xếp MUIKHOANTARO |
| Mũi khoan bê tông không rõ hãng | `MUIKHOANTARO` (211) | Không có hãng, xếp theo chức năng |
| Chổi than máy khoan MAKITA | `PTMAKITA` (235) | Linh kiện sửa máy, không phải đồ làm việc |
| Lưỡi cắt gạch MAKITA | `PKMAKITA` (169) | Gắn vào máy để làm việc |
| Cờ lê lực KINGTONY | `COLELUC` (252) | KINGTONY không có nhóm riêng, có nhóm chức năng chuyên biệt |
| Tuốc nơ vít ASAKI | `DUNGCUTHUONG` (249) | ASAKI không có nhóm riêng, là thương hiệu loại thường |
| Mỡ bò SHELL | `MOBIL, SHELL` (202) | Hãng có nhóm riêng |
| Mỡ bò không rõ hãng | `MOKHAC` (204) | Không có hãng |
| Ống PVC BÌNH MINH | `DUONGONGNHUA` (209) | BÌNH MINH không có nhóm riêng |
| Vòi phun áp lực KARCHER | `KARCHER-CN` (246) | Hãng có nhóm riêng, hàng công nghiệp |

---

## 5. CẤM

- Tự bịa nhóm mới không có trong tài liệu này.
- Dùng ID mà chưa xác nhận bằng `search_category_misa`.
- Nhảy thẳng sang `DANHMUCKHAC` khi chưa chạy hết lộ trình mục 1.
- Xếp hàng có hãng vào nhóm chức năng khi hãng đó có nhóm riêng.
