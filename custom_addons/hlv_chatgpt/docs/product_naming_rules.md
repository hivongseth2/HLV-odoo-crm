# QUY TẮC ĐẶT TÊN VÀ MÃ HÀNG HLV

Tài liệu tra cứu bắt buộc. Phải đọc tài liệu này trước khi đề xuất bất kỳ tên hàng
hoặc mã hàng nào. Nếu nội dung ở đây khác với những gì đang nhớ, lấy tài liệu này
làm chuẩn.

---

## 1. CHUẨN HÓA TÊN TRƯỚC KHI SEARCH

Bắt buộc chuẩn hóa trước mọi lần tìm kiếm. Mục tiêu: quy mọi cách gọi tự do của
sale về một tên chuẩn duy nhất.

### 1.1 Bảng quy đổi cách gọi

| Người dùng gõ | Hiểu là | Ghi chú |
|---|---|---|
| `phi 60`, `D60`, `Ø60`, `60` | đường kính 60mm | chỉ quy đổi khi ngữ cảnh đủ rõ là đường kính |
| `3ly`, `3li`, `3t`, `3mm` | độ dày 3mm | `ly` và `t` (tấc) đều là cách gọi miệng của mm |
| `60x3`, `60*3`, `60-3` | 60x3mm | chuẩn hóa dấu nhân thành `x` |
| `4m`, `4 mét`, `cây 4m` | chiều dài 4m | thường là quy cách cây/ống |
| `1p`, `1 phân`, `1"` | 1 inch | chỉ với vật tư đường ống |

### 1.2 Lỗi chính tả hãng thường gặp

| Gõ sai | Đúng |
|---|---|
| Bình Mình, Binh Minh | Bình Minh |
| MITSUBOCHI, Mitsuboshi | MITSUBOSHI |
| Makita, MAKITA | MAKITA |
| Kingtony, King Tony | KINGTONY |
| Karcher, Kacher | KARCHER |

Tên hãng trong TÊN HÀNG viết IN HOA.

### 1.3 Khi tên còn mơ hồ

Nếu cách gọi của người dùng có thể là dạng nói tắt của một hàng đã chuẩn hóa được,
**phải hỏi xác nhận trước**, không được tự nhảy sang đề xuất tạo mới.

> Anh/chị xác nhận giúp em: có phải hàng "Ống PVC Bình Minh" quy cách 60x3mm không ạ?

Ở giai đoạn này chỉ được dùng câu "em đang ghi nhận", **tuyệt đối chưa đưa ra đề xuất
tạo mới**. Đề xuất rồi mới hỏi lại là gây nhầm lẫn.

### 1.4 Một sản phẩm, nhiều cách gọi

Coi các trường hợp sau **có thể** là cùng một sản phẩm, phải search để loại trừ:

- khác thứ tự từ: "Ống PVC Bình Minh 60x3" ~ "Ống 60x3 PVC Bình Minh"
- thêm/bớt từ loại: "Ống nhựa PVC" ~ "Ống PVC"
- khác cách ghi kích thước: "60x3mm" ~ "D60x3" ~ "phi 60 dày 3"
- khác cách gọi hãng: "Bình Minh" ~ "BM"

---

## 2. TÊN HÀNG

### 2.1 Cấu trúc

```
[Tên loại chuẩn] [Mã model nếu có] [Thông số định danh] [HÃNG]
```

Ví dụ đúng:

- `Dây curoa cao su B67 MITSUBOSHI`
- `Lục giác bi AK-6402 2mm ASAKI`
- `Ống PVC 60x3mm BÌNH MINH`
- `Máy khoan pin FPD3-502X MILWAUKEE`

### 2.2 Thông số nào được đưa vào tên

Chỉ đưa vào tên **thông số định danh** — tức thông số dùng để phân biệt sản phẩm này
với các biến thể cùng dòng. Thông thường là **một**, tối đa **hai**.

| Loại hàng | Thông số định danh đưa vào tên |
|---|---|
| Vật tư đường ống, dây, thanh | kích thước / quy cách (60x3mm) |
| Dây curoa | mã dây (B67) |
| Dụng cụ cầm tay | cỡ (2mm, 10x200mm) |
| Máy | mã model (FPD3-502X) |
| Vòng bi, bạc đạn | mã vòng bi (6204-2RS) |
| Hóa chất, dầu mỡ | dung tích / khối lượng (5L, 400g) |

Màu sắc **chỉ** vào tên khi màu là yếu tố phân biệt mã hàng (ví dụ bạt, sơn, dây điện).

**Toàn bộ thông số — kể cả thông số đã có trong tên — vẫn phải ghi đầy đủ trong
description.** Tên là để người đọc nhận ra; description là để AI đọc và so khớp khi
đối chiếu trùng. Hai chỗ phục vụ hai mục đích khác nhau, không phải lặp thừa.

### 2.3 Cấm

- Nhồi toàn bộ thông số vào tên. Sai: `Ống PVC 60x3mm dài 4m màu trắng nhựa PVC BÌNH MINH`
- Thêm thông tin không có trong dữ liệu người dùng cung cấp.
- Từ ngữ bán hàng: "hàng chính hãng", "loại tốt", "giá rẻ", "xịn".
- **Tại bước gọi `create_product_misa`: bắt buộc dùng chính xác 100% tên đã được người
  dùng xác nhận OK.** Nghiêm cấm tự đổi tên, chuẩn hóa lại, rút gọn hay bổ sung ở bước
  này. Muốn sửa tên thì phải sửa trước khi xin xác nhận.

---

## 3. MÃ HÀNG

### 3.1 Cấu trúc

```
[MÃ_ĐỊNH_DANH]-[HÃNG]     khi có hãng
[MÃ_ĐỊNH_DANH]            khi không có hãng
```

Dấu `-` cuối cùng là dấu ngăn cách hãng. Các dấu `-` đứng trước thuộc về mã định danh.

- `B67-MITSUBOSHI`
- `AK6402-ASAKI`
- `14621008-KINGTONY`
- `HF8-4040-DOWTECH` (mã định danh là `HF8-4040`, hãng là `DOWTECH`)

### 3.2 MÃ_ĐỊNH_DANH lấy từ đâu

Theo thứ tự ưu tiên, dừng ở bước đầu tiên có kết quả:

**Ưu tiên 1 — Người dùng tự đưa mã.** Lấy đúng mã người dùng đưa, không sửa.
Một số hàng phải đặt mã theo NCC để tiện đổ báo cáo; đó là chủ ý, không phải sai sót.

**Ưu tiên 2 — Mã model / part number của hãng.** Giữ nguyên, viết IN HOA, bỏ khoảng
trắng. Ví dụ `AK-6402` → `AK6402`, `B67` → `B67`.

**Ưu tiên 3 — Tự sinh.** Khi hàng không có mã model nào:

```
[VIẾT TẮT LOẠI][THÔNG SỐ CỐT LÕI]
```

- Viết tắt loại: **ưu tiên dùng lại viết tắt đã có trong kho** cho loại hàng đó — tìm
  được qua kết quả search ở bước quét trùng. Nếu kho chưa có, ghép các từ chính, tối đa
  10 ký tự. Ví dụ "Ống nhựa PVC" → `ONGPVC`.
- Thông số cốt lõi: viết liền, bỏ đơn vị. `60x3mm` → `60X3`.
- Kết quả: `ONGPVC60X3-BINHMINH`

**Không bao giờ để mã trống.** Nếu không đủ dữ liệu để sinh mã theo cả 3 ưu tiên trên
thì đó là dấu hiệu thông tin quá nghèo nàn — xem mục 5.

### 3.3 Ký tự cho phép

- Chỉ `A-Z`, `0-9`, `-`, `.`
- IN HOA, không dấu tiếng Việt, không khoảng trắng.
- Cấm `*`, `/`, `#`, `+`, `,`, dấu ngoặc.

Sai: `ONPVC-60*3-BM`, `PVC D60X3X4M`, `Ống PVC 60x3`

### 3.4 Ngoại lệ KARCHER

Hàng KARCHER dùng **nguyên mã part number của hãng, giữ cả dấu chấm, và KHÔNG nối
hậu tố hãng** — vì mã Karcher đã là định danh duy nhất.

- `Khớp nối đực KARCHER` → mã `2.115-001.0`
- `Vòi phun KARCHER` → mã `4.767-012.0`

---

## 4. MÔ TẢ (DESCRIPTION) — CHUỖI JSON

Field `Description` là kiểu string, nhưng **nội dung bắt buộc phải là một chuỗi JSON
hợp lệ** để sau này trích xuất tự động được.

### 4.1 Danh sách key

Key viết không dấu, `snake_case`. Value là chuỗi, **được phép có dấu tiếng Việt**.

```
kich_thuoc, mau_sac, chat_lieu, model, hang, cong_suat, ap_luc,
chieu_dai, duong_kinh, do_day, dien_ap, trong_luong, xuat_xu, ghi_chu
```

Chỉ đưa key **thực sự có dữ liệu**. Không bịa key rỗng, không thêm thông tin không có.

### 4.2 Ví dụ hợp lệ

```json
{"kich_thuoc":"60x3mm","chat_lieu":"PVC","hang":"BÌNH MINH","mau_sac":"trắng"}
```

```json
{"model":"14621008","kich_thuoc":"10x200mm","hang":"KINGTONY"}
```

Kiểm tra trước khi gửi: mọi key và mọi value đều nằm trong cặp nháy kép, có dấu phẩy
ngăn cách, mở `{` đóng `}` đầy đủ.

### 4.3 Khi nói với người dùng

**Không bao giờ hiển thị JSON cho người dùng.** Phải dịch sang tiếng Việt:

`{"mau_sac":"xanh trắng","chat_lieu":"nhựa","xuat_xu":"Việt Nam"}`

nói thành:

> Màu sắc: xanh trắng. Chất liệu: nhựa. Xuất xứ: Việt Nam.

---

## 5. CHECKLIST ĐỦ THÔNG TIN ĐỂ TẠO

Chỉ được đề xuất tạo mới khi có **đủ cả 4 mục bắt buộc**:

| # | Mục | Bắt buộc | Nếu thiếu |
|---|---|---|---|
| 1 | Tên loại hàng rõ ràng | Có | hỏi lại |
| 2 | Mã định danh (theo mục 3.2) | Có | hỏi lại |
| 3 | Nhóm hàng | Có | tra theo tài liệu phân nhóm |
| 4 | Đơn vị tính | Có | suy luận nếu chắc chắn, không thì hỏi |
| 5 | Thông số định danh | Có, trừ khi hàng không có biến thể | hỏi lại |
| 6 | Màu sắc | Chỉ khi là yếu tố phân biệt | nhắc người dùng bổ sung |
| 7 | Thuế GTGT / Giá nhập / Giá bán | Không | điền 0 |

**Xác nhận "OK" của người dùng không thay thế được checklist này.** Nếu người dùng bảo
OK mà mục 1-5 còn thiếu, phải hỏi lại đang OK cái gì, hoặc yêu cầu bổ sung, hoặc mời
liên hệ chị Duyên.

---

## 6. VÍ DỤ HOÀN CHỈNH

### Ví dụ A — có mã hãng, có hãng

Người dùng: *"tạo con lục giác bi asaki 2 ly mã AK-6402"*

| Trường | Giá trị |
|---|---|
| Tên hàng | `Lục giác bi AK-6402 2mm ASAKI` |
| Mã hàng | `AK6402-ASAKI` |
| Description | `{"model":"AK-6402","kich_thuoc":"2mm","hang":"ASAKI"}` |

### Ví dụ B — không có mã hãng, phải tự sinh

Người dùng: *"ống pvc bình minh 60x3 cây 4m"*

| Trường | Giá trị |
|---|---|
| Tên hàng | `Ống PVC 60x3mm BÌNH MINH` |
| Mã hàng | `ONGPVC60X3-BINHMINH` |
| Description | `{"kich_thuoc":"60x3mm","chieu_dai":"4m","chat_lieu":"PVC","hang":"BÌNH MINH"}` |

Lưu ý: chiều dài 4m là quy cách phụ nên chỉ nằm ở description, không vào tên.

### Ví dụ C — hàng KARCHER

Người dùng: *"khớp nối đực karcher 2.115-001.0"*

| Trường | Giá trị |
|---|---|
| Tên hàng | `Khớp nối đực 2.115-001.0 KARCHER` |
| Mã hàng | `2.115-001.0` |
| Description | `{"model":"2.115-001.0","hang":"KARCHER"}` |

### Ví dụ D — thông tin quá nghèo, từ chối

Người dùng: *"tạo giúp cái ống nhựa"*

Không có hãng, không có kích thước, không có mã. Không đủ mục 2 và 5 của checklist.

> Ống nhựa loại gì ạ? Em cần hãng và quy cách (phi bao nhiêu, dày bao nhiêu) mới tạo
> được mã. Thông tin thế này em chịu.

Tuyệt đối **không** đề xuất tạo mới rồi mới hỏi bổ sung.
