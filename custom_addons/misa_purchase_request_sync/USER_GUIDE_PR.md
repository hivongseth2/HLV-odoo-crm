# TÀI LIỆU HƯỚNG DẪN SỬ DỤNG
# PHÂN HỆ YÊU CẦU MUA HÀNG (PURCHASE REQUEST)

**Phiên bản:** 1.0  
**Ngày cập nhật:** 15/07/2026  
**Đối tượng sử dụng:** Bộ phận Kinh doanh (Sale), Kế toán, Thủ kho, Quản lý

---

## MỤC LỤC

1. [Giới thiệu tổng quan](#phần-1-giới-thiệu-tổng-quan)
2. [Tạo Yêu cầu Mua hàng](#phần-2-tạo-yêu-cầu-mua-hàng)
   - 2.1. [Tạo thủ công trên Odoo](#21-tạo-thủ-công-trên-odoo)
   - 2.2. [Đồng bộ từ MISA CRM](#22-đồng-bộ-ycmh-từ-misa-crm)
3. [Quy trình Phê duyệt](#phần-3-quy-trình-phê-duyệt)
4. [Tạo Đơn mua hàng từ YCMH](#phần-4-tạo-đơn-mua-hàng-từ-ycmh)
5. [Nhập kho & Theo dõi tiến độ](#phần-5-nhập-kho--theo-dõi-tiến-độ)
6. [Các tình huống đặc biệt](#phần-6-các-tình-huống-đặc-biệt)
7. [Câu hỏi thường gặp](#phần-7-câu-hỏi-thường-gặp-faq)

---

## PHẦN 1: GIỚI THIỆU TỔNG QUAN

### 1.1. Mục đích

Phân hệ **Yêu cầu Mua hàng (Purchase Request - PR)** cho phép các bộ phận (Sale, Kế toán, Kho, Sản xuất...) gửi yêu cầu mua sắm vật tư, hàng hóa, dịch vụ lên bộ phận Thu mua một cách tập trung, có kiểm soát.

### 1.2. Luồng xử lý cơ bản

```
Người yêu cầu (Sale/Kế toán)
    │
    ├─ Tạo YCMH thủ công trên Odoo
    └─ Hoặc được đồng bộ tự động từ MISA CRM
    │
    ▼
Trạng thái "Nháp" (Draft) → [Yêu cầu phê duyệt]
    │
    ▼
Trạng thái "Chờ phê duyệt" (To Approve)
    │
    ├─ [Phê duyệt] → "Đang thực hiện" (In Progress)
    └─ [Từ chối]   → "Từ chối" (Rejected) → [Thiết lập lại] → quay về Nháp
    │
    ▼
Bộ phận Mua hàng nhấn [Tạo RFQ]
    │
    ├─ Tạo Đơn mua hàng mới (PO)
    └─ Gộp vào Đơn mua hàng đã có
    │
    ▼
Nhà cung cấp giao hàng → Thủ kho nhập kho → Kế toán ghi nhận
    │
    ▼
YCMH tự động cập nhật tiến độ → Hoàn thành
```

<!-- ![Hình ảnh 1: Sơ đồ luồng xử lý Yêu cầu Mua hàng] -->

### 1.3. Các trạng thái của Yêu cầu Mua hàng

| Trạng thái | Mô tả | Ai thao tác? |
|------------|-------|--------------|
| **Nháp** (Draft) | Mới tạo, có thể sửa/xóa | Người yêu cầu |
| **Chờ phê duyệt** (To Approve) | Đã gửi, chờ quản lý xem xét | Người yêu cầu (bấm gửi) |
| **Đã phê duyệt** (Approved) | Đã được duyệt (có thể đã chuyển sang Đang thực hiện) | Quản lý |
| **Đang thực hiện** (In Progress) | Đã phê duyệt, đã có PO hoặc đang mua hàng | Hệ thống tự động |
| **Hoàn thành** (Done) | Đã nhập kho đầy đủ | Quản lý |
| **Từ chối** (Rejected) | Không được chấp thuận | Quản lý |

---

## PHẦN 2: TẠO YÊU CẦU MUA HÀNG

*Đa số YCMH được đồng bộ tự động từ MISA CRM. Trường hợp cần tạo thủ công, thao tác như sau:*

### 2.1. Tạo thủ công trên Odoo

Vào **Purchase Requests** → **[Mới]** → Điền các thông tin chính (Số tham chiếu, Người yêu cầu, Mô tả, **Đơn bán hàng liên quan**, **Địa điểm giao**) → Tab **Sản phẩm** → thêm hàng hóa → **[Lưu]** → **[Yêu cầu phê duyệt]**.

Các trường **Đơn bán hàng liên quan** và **Địa điểm giao** là trường mở rộng giúp việc đối chiếu và theo dõi sau này.

<!-- ![Hình ảnh 2: Form tạo YCMH thủ công trên Odoo] -->

---

### 2.2. Đồng bộ YCMH từ MISA CRM

YCMH được đồng bộ tự động từ MISA CRM về Odoo thông qua tiện ích mở rộng (Browser Extension) trên Chrome.

#### Các thông tin trên giao diện MISA CRM

##### 1. Các thông tin chung (Phần đầu phiếu)
- **Mục đích mua sắm**: Nhập lý do/mục đích mua sắm.
- **Địa điểm giao**: Nơi nhận hàng (sẽ đồng bộ sang trường **Địa điểm giao** trên Odoo).
- **Cơ hội**: Cơ hội bán hàng liên quan trên MISA CRM.
- **Hạn giao hàng mong muốn**: Hạn giao hàng mong muốn của phiếu.
- **Đơn hàng**: Số đơn bán hàng liên quan trên Odoo (sẽ đồng bộ sang trường **Đơn bán hàng liên quan**).
- **ID Quy trình**: Mã/ID của quy trình liên quan.

##### 2. Chi tiết hàng hóa (Tab "Thông tin hàng hóa")
Bảng thông tin hàng hóa bao gồm các thông tin mặc định của MISA CRM và các cột mở rộng do **Odoo Extension** tự động bổ sung từ Odoo (tính từ cột **Nhà cung cấp** trở đi):

| Cột trên MISA CRM | Loại cột | Ghi chú / Ý nghĩa |
|-------------------|-----------|-------------------|
| **STT** | Mặc định | Số thứ tự dòng hàng. |
| **Mã hàng hóa** | Mặc định | Mã sản phẩm (SKU). Nếu sản phẩm chưa có trên Odoo, hệ thống sẽ tự động tạo mới khi đồng bộ. |
| **Nhà cung cấp** | Extension tạo | Nhà cung cấp đề xuất cho sản phẩm này. Nếu là NCC mới, hệ thống sẽ tạo ghi chú cảnh báo trong Chatter trên Odoo. |
| **Tồn kho** | Extension tạo | Số lượng tồn kho thực tế hiện tại của sản phẩm này được lấy trực tiếp từ Odoo. |
| **SL đã chọn** | Extension tạo | Số lượng sản phẩm đã được chọn để thực hiện mua/giao. |
| **SL chưa giao** | Extension tạo | Số lượng sản phẩm chưa được giao từ các đơn hàng liên quan trên Odoo. |
| **Đơn giá trước thuế** | Extension tạo | Đơn giá của hàng hóa trước thuế (đồng bộ từ Odoo hoặc lấy từ MISA). |
| **% Chiết khấu** | Extension tạo | Tỷ lệ chiết khấu được áp dụng cho dòng sản phẩm. |
| **Tiền chiết khấu** | Extension tạo | Số tiền chiết khấu được tính tự động dựa trên số lượng, đơn giá và % chiết khấu. |
| **% Thuế** | Extension tạo | Thuế suất VAT của mặt hàng (10%, 8%, 5%...). |
| **Tiền... (Tiền thuế)** | Extension tạo | Số tiền thuế GTGT tương ứng của dòng hàng. |

> 💡 **Mẹo:** Các cột do Extension tạo giúp người dùng theo dõi nhanh tồn kho, trạng thái giao hàng, đơn giá đề xuất và các thông tin thuế/chiết khấu trực tiếp trên giao diện MISA CRM mà không cần phải mở Odoo.

#### Thao tác đồng bộ

1. Nhấp vào liên kết **Cập nhật hàng hóa** ở góc phải phần "Thông tin hàng hóa" để làm mới dữ liệu từ Odoo sang CRM.
2. Nhấn nút **Tạo YCMH Odoo** ở góc trên cùng bên phải giao diện MISA CRM để bắt đầu đồng bộ.

Hệ thống sẽ kiểm tra trùng, tạo mới hoặc cập nhật YCMH, tự động tạo sản phẩm mới (nếu chưa có) và ghi nhận NCC mới vào Chatter. Sau khi đồng bộ thành công, YCMH sẽ được tạo ở trạng thái **Chờ phê duyệt** trên Odoo.

---

## PHẦN 3: QUY TRÌNH PHÊ DUYỆT

*Dành cho Cấp Quản lý, Trưởng bộ phận, người được ủy quyền phê duyệt.*

### 3.1. Xem danh sách chờ phê duyệt

1. Vào ứng dụng **Purchase Requests**.
2. Trên thanh tìm kiếm, nhấn bộ lọc **Chờ phê duyệt** (To Approve) để chỉ hiện các YCMH cần xử lý.

<!-- ![Hình ảnh 10: Bộ lọc Chờ phê duyệt trên thanh tìm kiếm] -->

3. Ngoài ra, bạn có thể dùng các bộ lọc nhanh khác:
   - **Giao cho tôi**: YCMH được giao cho bạn phê duyệt (field Người phê duyệt).
   - **Yêu cầu của tôi**: YCMH do bạn tạo.
   - **Tin nhắn chưa đọc**: Các YCMH có chat chưa xem.

### 3.2. Phê duyệt YCMH

1. Nhấn vào YCMH cần xem xét để mở form chi tiết.
2. Kiểm tra các thông tin:
   - Người yêu cầu và mục đích mua (phần Mô tả, Tài liệu gốc).
   - Nếu có **Đơn bán hàng liên quan** → kiểm tra xem đơn hàng có đúng không.
   - Danh sách hàng hóa: số lượng, ngày mong muốn có hợp lý không.
   - **Địa điểm giao**: đã chọn đúng nơi nhận hàng chưa.
3. Nếu đồng ý: nhấn nút **[Phê duyệt]** (Approve).  
   - YCMH chuyển sang trạng thái **Đã phê duyệt** (Approved) → sau đó tự động chuyển sang **Đang thực hiện** (In Progress).  
   - Bộ phận Mua hàng sẽ nhận được thông báo và có thể bắt đầu lập Đơn mua hàng.

<!-- ![Hình ảnh 11: Nút Phê duyệt trên form YCMH] -->

### 3.3. Từ chối YCMH

Nếu yêu cầu chưa phù hợp (sai số lượng, vượt ngân sách, thiếu thông tin...):

1. Nhấn nút **[Từ chối]** (Reject).
2. YCMH chuyển sang trạng thái **Từ chối** (Rejected).
3. **Khuyến nghị:** Viết lý do từ chối vào Chatter (hộp thư bên dưới) để người yêu cầu biết và điều chỉnh.

<!-- ![Hình ảnh 12: Nút Từ chối và hộp Chatter để ghi lý do] -->

### 3.4. Sau khi từ chối - Người yêu cầu sửa lại

1. Người yêu cầu mở YCMH bị từ chối.
2. Nhấn nút **[Thiết lập lại]** (Reset to Draft) (nút này chỉ hiện với người có quyền Quản lý).
3. Chỉnh sửa thông tin theo yêu cầu của quản lý.
4. Nhấn lại **[Yêu cầu phê duyệt]** để gửi duyệt lần 2.

> ⚠️ **Lưu ý:** Nếu YCMH đã được tạo Đơn mua hàng (PO), không thể **Thiết lập lại** về Nháp.

<!-- ![Hình ảnh 13: Nút Thiết lập lại trên form YCMH] -->

---

## PHẦN 4: TẠO ĐƠN MUA HÀNG TỪ YCMH

*Dành cho Bộ phận Mua hàng (Purchasing).*

Sau khi YCMH được phê duyệt và chuyển sang trạng thái **Đang thực hiện** (In Progress), bộ phận Mua hàng sẽ tạo Đơn mua hàng (Purchase Order / RFQ) từ YCMH.

### 4.1. Mở Wizard "Tạo RFQ"

1. Mở YCMH đã phê duyệt.
2. Nhấn nút **[Tạo RFQ]** (Create RFQ) ở góc trên bên trái (nút này chỉ xuất hiện ở trạng thái "Đã phê duyệt" hoặc "Đang thực hiện").

<!-- ![Hình ảnh 14: Nút Tạo RFQ trên form YCMH] -->

3. Cửa sổ **Tạo Yêu cầu báo giá** (Purchase Request Line Make Purchase Order) hiện ra với các phân vùng sau:

<!-- ![Hình ảnh 15: Cửa sổ Wizard Tạo RFQ] -->

### 4.2. Phân vùng "RFQ HIỆN CÓ ĐỂ CẬP NHẬT"

Phần này cho phép **gộp** các mặt hàng trong YCMH vào một Đơn mua hàng (PO) **đã có** (đang ở trạng thái Nháp/Draft).

| Trường | Mô tả |
|--------|-------|
| **Đơn đặt hàng** (Purchase Order) | Chọn PO draft có sẵn để gộp. **Để trống** nếu muốn tạo PO mới. |
| **Chỉ gộp nếu trùng Ngày dự kiến** | Nếu bật, chỉ cộng dồn số lượng nếu trùng cả sản phẩm và ngày dự kiến. Nếu khác ngày → tạo dòng riêng. |
| **Nhà cung cấp chung** (Supplier) | *(Tùy chọn)* Chọn NCC cho tất cả các dòng bên dưới. Nếu để trống → từng dòng chọn NCC riêng. |

**Cách dùng phổ biến:**
- **Tạo PO mới:** Để trống "Đơn đặt hàng" → nhập "Nhà cung cấp" → nhấn [Tạo RFQ].
- **Gộp vào PO cũ:** Chọn PO đang làm dở → nhấn [Tạo RFQ] → hệ thống tự thêm dòng hoặc cộng dồn số lượng.

### 4.3. Danh sách hàng hóa đề xuất

Phần dưới của wizard hiển thị danh sách các mặt hàng được trích xuất từ YCMH:

| Cột | Cách dùng |
|-----|-----------|
| **Sản phẩm** | Tên sản phẩm (read-only từ YCMH) |
| **Mô tả** | Có thể sửa nếu muốn giữ mô tả riêng cho PO |
| **Số lượng cần mua** | Nhập số lượng thực tế đặt mua lần này. Có thể đặt ít hơn YCMH, phần còn lại sẽ đặt đợt sau. |
| **ĐVT** | Đơn vị tính (tự động) |
| **Nhà cung cấp** | Chọn NCC cho từng mặt hàng (nếu không chọn NCC chung ở trên) |
| **Chi phí ước tính** | Giá dự kiến |
| **Lấy mô tả từ YCMH** (checkbox) | Bật để giữ nguyên mô tả chi tiết từ YCMH. Luôn tạo dòng riêng (không gộp). |
| **Lấy giá dự trù làm giá mua** (checkbox) | Bật để lấy giá dự kiến làm giá mua. Luôn tạo dòng riêng. |
| **Xóa (thùng rác)** | Xóa mặt hàng khỏi đợt đặt này (vẫn giữ trên YCMH). |

<!-- ![Hình ảnh 16: Danh sách hàng hóa trong wizard Tạo RFQ] -->

### 4.4. Hoàn tất tạo RFQ

1. Kiểm tra lại danh sách hàng hóa, số lượng, nhà cung cấp.
2. Nhấn nút **[Tạo RFQ]** ở góc dưới bên trái.
3. Hệ thống sẽ tạo **Request for Quotation (RFQ)** / **Purchase Order (PO)**.
4. Sau khi tạo thành công:
   - Form YCMH xuất hiện **Smart Button** hình xe tải với nhãn **[Đơn mua hàng]** và số lượng PO.
   - Nhấn vào Smart Button để chuyển đến PO vừa tạo.

<!-- ![Hình ảnh 17: Smart Button Đơn mua hàng trên form YCMH] -->

### 4.5. Hoàn thiện PO

1. Tại form PO, cập nhật:
   - **Đơn giá** đã thương lượng với NCC.
   - **Thuế suất**, điều khoản thanh toán.
   - **Ngày dự kiến giao hàng**.
2. Khi đã thống nhất với NCC, nhấn **[Xác nhận Đơn hàng]** (Confirm Order) để chuyển RFQ thành **Purchase Order (PO)** chính thức.
3. Hệ thống sẽ tự động tạo **Phiếu nhận hàng (Receipt)** → thủ kho sẽ nhập kho sau.

---

## PHẦN 5: NHẬP KHO & THEO DÕI TIẾN ĐỘ

*Dành cho Thủ kho & Kế toán.*

### 5.1. Nhập kho từ PO

1. Khi hàng về, thủ kho vào ứng dụng **Kho (Inventory)** → **Nhận hàng (Receipts)**.
2. Tìm phiếu nhận hàng tương ứng với PO đã xác nhận.
3. Kiểm tra số lượng thực tế, nhập vào cột **Hoàn thành (Done)**.
4. Nhấn **[Xác nhận]** (Validate) để hoàn tất nhập kho.

<!-- ![Hình ảnh 18: Giao diện Phiếu nhận hàng] -->

**Kết quả:** Ngay sau khi xác nhận, số lượng đã nhận sẽ tự động cập nhật ngược về YCMH ban đầu. Kế toán có thể xem được toàn bộ tiến độ từ gốc đến ngọn.

### 5.2. Theo dõi tiến độ YCMH

Trên form YCMH, có các Smart Button giúp theo dõi nhanh:

| Smart Button | Ý nghĩa |
|-------------|---------|
| **Dòng** (Lines) | Tổng số dòng hàng hóa trong YCMH. Nhấn vào để xem chi tiết. |
| **Đơn mua hàng** (PO) | Số lượng PO đã tạo từ YCMH này. Nhấn vào để xem danh sách PO. |
| **Phiếu lấy hàng** (Receipts) | Số lượng phiếu nhập kho đã xác nhận. Nhấn vào để xem chi tiết. |

<!-- ![Hình ảnh 19: Các Smart Button trên form YCMH] -->

### 5.3. Cột tiến độ trên danh sách

Khi xem **danh sách YCMH**, hệ thống hiển thị cột **Tiến độ (Progress)** giúp bạn biết ngay tình trạng mà không cần mở từng phiếu:

- **ĐH 2/5 • NK 1/5** → Đã tạo Đơn mua: 2/5 dòng, đã nhập kho: 1/5 dòng.
- **ĐH 0/5 • NK 0/5** → Chưa tạo PO (chỉ mới phê duyệt).
- **ĐH 5/5 • NK 5/5** → Hoàn thành tất cả.

<!-- ![Hình ảnh 20: Cột tiến độ trên danh sách YCMH] -->

### 5.4. Xem chi tiết từng dòng

Trong tab **Sản phẩm** của YCMH, mỗi dòng hàng hiển thị:

| Trường | Ý nghĩa |
|--------|---------|
| **Số lượng** (Qty) | Số lượng yêu cầu ban đầu |
| **Số lượng RFQ/PO** (Purchased Qty) | Số lượng đã lên Đơn mua hàng |
| **Trạng thái mua** (Purchase State) | Trạng thái của PO liên quan (Draft, Sent, Purchase, Done, Cancel) |
| **Nút chi tiết** (icon danh sách) | Nhấn để xem thông tin mở rộng của dòng (tồn kho, đã nhận, đã hủy...) |

<!-- ![Hình ảnh 21: Các cột thông tin trên danh sách dòng hàng] -->

---

## PHẦN 6: CÁC TÌNH HUỐNG ĐẶC BIỆT

### 6.1. YCMH có Nhà cung cấp mới từ MISA CRM

Khi đồng bộ YCMH từ MISA CRM, nếu phiếu mua hàng có thông tin **Nhà cung cấp chưa tồn tại trên Odoo**, hệ thống sẽ:

1. **Không tự động tạo** NCC mới (tránh tạo dữ liệu rác).
2. Ghi thông tin NCC đề xuất vào **Chatter** (hộp thư) của YCMH với định dạng:

   > NCC mới từ MISA cần kiểm tra:
   > - Mã SP: [Mã sản phẩm]  
   > - Tên NCC: [Tên NCC]  
   > - Địa chỉ: [Địa chỉ]  
   > - Điện thoại: [Số điện thoại]  
   > - MST: [Mã số thuế]

3. Bộ phận Mua hàng cần **kiểm tra thông tin** và tạo NCC trên Odoo (nếu hợp lệ), sau đó gán vào dòng hàng tương ứng.

<!-- ![Hình ảnh 22: Thông báo NCC mới trong Chatter] -->

### 6.2. Điều chỉnh YCMH sau khi đã gửi duyệt

Nếu cần sửa YCMH đang ở trạng thái **Chờ phê duyệt** hoặc **Từ chối**:

1. **Trường hợp chờ duyệt:** Yêu cầu người phê duyệt **Từ chối** → sau đó người tạo **Thiết lập lại** (Reset to Draft) → sửa → gửi duyệt lại.
2. **Trường hợp đã từ chối:** Người tạo (có quyền Quản lý) nhấn **[Thiết lập lại]** → sửa → gửi duyệt lại.
3. **Trường hợp đã có PO:** Không thể Thiết lập lại. Phải điều chỉnh trên PO hoặc tạo YCMH mới.

> ⚠️ **Quan trọng:** Nếu YCMH đã có PO (dù là Draft), nút Thiết lập lại sẽ **không khả dụng**.

### 6.3. Hủy dòng / Hủy YCMH

**Hủy 1 dòng hàng:**
- Ở trạng thái **Nháp**: Xóa dòng trực tiếp.
- Ở trạng thái **Đang thực hiện**: Không thể xóa. Phải hủy qua PO tương ứng.

**Hủy toàn bộ YCMH:**
- Ở trạng thái **Nháp**: Nhấn biểu tượng thùng rác để xóa.
- Ở trạng thái khác: Quản lý nhấn **[Từ chối]** (Reject) để kết thúc.

> 💡 Khi tất cả các dòng hàng bị hủy (cancelled), YCMH tự động chuyển sang trạng thái **Từ chối**.

### 6.4. YCMH có Đơn bán hàng liên quan

Khi tạo YCMH từ MISA CRM, nếu có chọn **Số ĐH liên quan (SaleOrderIDText)**, YCMH sẽ được liên kết với đơn bán hàng tương ứng trên Odoo.

Điều này giúp:
- Kế toán dễ dàng đối chiếu chi phí mua hàng với doanh thu bán hàng.
- Quản lý biết được YCMH này phục vụ cho đơn hàng nào.
- Truy xuất nguồn gốc: Từ Đơn bán → YCMH → PO → Nhập kho.

---

## PHẦN 7: CÂU HỎI THƯỜNG GẶP (FAQ)

### 7.1. Làm sao biết YCMH đã được tạo PO chưa?

- **Trên form chi tiết:** Nhìn Smart Button **Đơn mua hàng** (PO). Nếu số > 0 là đã có PO.
- **Trên danh sách:** Nhìn cột **Tiến độ**. Nếu có "ĐH 1/5..." là đã tạo PO cho ít nhất 1 dòng.
- **Trên tab Sản phẩm:** Cột **Số lượng RFQ/PO** hiển thị số lượng đã lên đơn.

### 7.2. Làm sao biết hàng đã nhập kho đủ chưa?

- **Trên danh sách:** Cột **Tiến độ** hiển thị "NK 3/5" = đã nhập 3/5 dòng.
- **Trên tab Sản phẩm:** Nhấn icon danh sách ở cuối mỗi dòng → mở form chi tiết → xem **Số lượng đã hoàn thành (qty_done)**.

### 7.3. Tôi có thể sửa YCMH sau khi đã phê duyệt không?

**Không.** Sau khi phê duyệt (trạng thái Đã phê duyệt / Đang thực hiện), YCMH bị khóa toàn bộ. Nếu cần thay đổi:
- **Nếu chưa có PO:** Yêu cầu quản lý Từ chối → Thiết lập lại → sửa → gửi duyệt lại.
- **Nếu đã có PO:** Phải sửa trực tiếp trên PO (hủy PO nếu cần).

### 7.4. YCMH từ MISA có tự động tạo sản phẩm mới không?

**Có.** Nếu mã sản phẩm trong YCMH từ MISA **chưa tồn tại trên Odoo**, hệ thống sẽ tự động tạo sản phẩm mới với:
- Mã: lấy từ trường Mã sản phẩm.
- Tên: lấy từ Tên sản phẩm.
- Đơn vị tính: lấy từ ĐVT (mặc định "Cái" nếu không có).
- Loại: Hàng hóa (consumable).
- Cho phép mua & bán.

> ✅ **Kiểm tra:** Vào **Sản phẩm (Products)** → tìm mã sản phẩm để xem thông tin đã tạo.

### 7.5. Tôi muốn đặt mua một phần, phần còn lại để đợt sau?

Khi nhấn **[Tạo RFQ]**, tại wizard bạn có thể:
- Nhập **số lượng cần mua** nhỏ hơn số lượng yêu cầu.
- Các dòng còn lại (chưa đặt đủ) vẫn giữ trên YCMH để đặt đợt sau.
- Khi đặt đợt sau, nhấn lại **[Tạo RFQ]** → hệ thống chỉ hiện các dòng còn tồn.

### 7.6. Làm sao để xóa YCMH?

- **Ở trạng thái Nháp:** Có thể xóa trực tiếp (nút thùng rác trên danh sách hoặc form).
- **Ở trạng thái khác:** Không thể xóa. Phải chuyển về Nháp (nếu chưa có PO) hoặc Từ chối.
- **Đã có PO:** Không thể xóa. Phải hủy PO trước, sau đó chuyển YCMH về Nháp để xóa.

### 7.7. Phân hệ này có dùng được cho dịch vụ không?

**Có.** Trong danh sách sản phẩm, bạn có thể chọn các sản phẩm loại **Dịch vụ (Service)**. Khi đó:
- Số lượng đã nhận (qty_done) sẽ được tính từ PO thay vì từ Phiếu nhập kho.
- Phù hợp cho việc yêu cầu mua dịch vụ bảo trì, tư vấn, thuê ngoài...

### 7.8. Ai có quyền phê duyệt YCMH?

Người có nhóm quyền **Quản lý YCMH (Purchase Request Manager)**. Nhóm quyền này do Quản trị hệ thống (Admin) cấu hình.

### 7.9. Làm sao xem lịch sử thay đổi của YCMH?

Tất cả thay đổi trạng thái (tạo, gửi duyệt, phê duyệt, từ chối, tạo PO...) đều được ghi lại trong **Chatter** (hộp thư ở cuối form YCMH). Bạn có thể:
- Xem ai đã làm gì, lúc nào.
- Đọc ghi chú từ người phê duyệt.
- Xem thông báo đồng bộ từ MISA CRM.

---

*Trên đây là toàn bộ hướng dẫn sử dụng Phân hệ Yêu cầu Mua hàng. Mọi thắc mắc hoặc góp ý, vui lòng liên hệ bộ phận IT / Quản trị hệ thống để được hỗ trợ.*