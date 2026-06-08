# 📖 HƯỚNG DẪN SỬ DỤNG: ỨNG DỤNG MÃ VẠCH (HLV MOBILE BARCODE)

Chào mừng bạn đến với tài liệu hướng dẫn sử dụng Ứng dụng Quét mã vạch Kho (HLV Mobile Barcode). Ứng dụng này được thiết kế tối ưu cho các thiết bị di động/máy quét mã vạch giúp tự động hoá quy trình nhập, xuất, và điều chuyển kho của bạn một cách nhanh chóng và chính xác.

---

## 1. Mở ứng dụng và Đăng nhập
Có 2 cách để mở ứng dụng quét mã vạch:
- **Cách 1 (Từ điện thoại/máy quét):** Đăng nhập vào Odoo, tại màn hình chính nhấn chọn ứng dụng **"Mobile Barcode"** (Biểu tượng mã vạch). Ứng dụng sẽ tự động bật camera và sẵn sàng quét. Bạn có thể quét ngay một mã phiếu kho (VD: `WH/PICK/00001`) để bắt đầu.
- **Cách 2 (Từ máy tính/tablet):** Trong giao diện Odoo Backend, mở một phiếu kho (Phiếu Nhập, Điều chuyển, hoặc Lấy hàng). Ở góc trên bên trái, nhấn vào nút **"Quét Mã Vạch"**. Ứng dụng sẽ mở ra và tự động tải luôn danh sách sản phẩm của phiếu đó.

---

## 2. Ý nghĩa các loại mã vạch hỗ trợ (Smart Scan)
Ứng dụng có tính năng **Smart Scan** (Quét thông minh). Bạn chỉ cần đưa mã vạch vào camera/máy quét, hệ thống sẽ tự hiểu bạn đang quét cái gì:
- 📄 **Quét Mã Phiếu (Picking):** Hệ thống tự động mở phiếu đó lên và tải danh sách sản phẩm.
- 📦 **Quét Mã Kiện Hàng (Package):** (VD: `PACK0001`). Hệ thống sẽ tự động hoàn thành quét cho TẤT CẢ các sản phẩm nằm trong kiện hàng đó cùng một lúc.
- 📍 **Quét Vị Trí (Location):** (VD: `WH/Stock/Kệ A`). Ứng dụng sẽ ghi nhận vị trí này. Khi bạn quét các sản phẩm tiếp theo, hệ thống sẽ hiểu là bạn đang "Lấy hàng từ vị trí này" hoặc "Cất hàng vào vị trí này" (Putaway).
- 🥫 **Quét Mã Sản phẩm (Barcode/SKU):** Quét từng sản phẩm. Mỗi lần quét thành công sẽ phát tiếng "Bíp", thanh tiến độ màu xanh sẽ tăng lên. Nếu quét lố số lượng yêu cầu hoặc sản phẩm sai, máy sẽ phát âm báo lỗi.

---

## 3. Thao tác trên từng loại phiếu

### 3.1 Phiếu Nhập Kho (Receipts)
Phiếu nhập kho dùng để nhận hàng từ nhà cung cấp.
1. Quét mã phiếu Nhập kho.
2. **Tuỳ chọn Putaway (Cất hàng):** Trước khi quét sản phẩm, hãy quét mã Vị trí (Ví dụ kệ tầng 1) để hệ thống biết bạn cất hàng vào đâu.
3. Quét từng sản phẩm một cho đến khi thanh màu xanh đầy.
4. Nếu nhà cung cấp giao một sản phẩm không có trong đơn, bạn vẫn có thể quét, hệ thống sẽ tự động thêm một dòng mới vào phiếu (nếu cấu hình kho cho phép).
5. Nhấn nút **Xác nhận (✔️)** ở góc phải màn hình để hoàn thành phiếu nhập.

### 3.2 Phiếu Lấy Hàng (Pick) & Điều Chuyển (Internal Transfers)
Phiếu lấy hàng dùng để gom hàng trong kho, hoặc chuyển từ kho này sang kho khác.
1. Quét mã phiếu Lấy hàng/Điều chuyển.
2. Di chuyển đến Vị trí nguồn (hệ thống có hiển thị vị trí gợi ý trên từng dòng).
3. **Cảnh báo Tồn Kho:** Nếu vị trí đó thực tế đã hết hàng, khi bạn quét, hệ thống sẽ chặn lại và báo lỗi *"Không có đủ tồn kho tại vị trí này"*. Bạn cần kiểm tra lại kho hoặc đi tìm vị trí khác có chứa sản phẩm.
4. **Giới hạn số lượng:** Bạn không thể quét lố số lượng yêu cầu (Demand). Nếu phiếu yêu cầu lấy 5 cái, quét đến cái thứ 6 hệ thống sẽ tít báo lỗi.

### 3.3 Quy trình Đóng gói (Put in Pack)
Ứng dụng hỗ trợ gom nhiều sản phẩm rời rạc thành 1 Kiện hàng (Thùng, Pallet...).
1. Quét mã các sản phẩm muốn đóng gói.
2. Nhấn vào biểu tượng **"Hộp Quà" (📦)** ở dưới cùng màn hình.
3. Hệ thống sẽ tự động gom các sản phẩm bạn vừa quét lại, tạo ra 1 mã kiện hàng mới (VD: `PACK00045`) và in nhãn cho kiện hàng đó.

---

## 4. Xử lý quy trình Điều chuyển 2 bước (Transit) qua 2 kho
Khi điều chuyển từ Kho A sang Kho B qua trung gian (Transit), Odoo tự sinh ra 2 phiếu (Bước 1 và Bước 2).

**Tại Bước 1 (Kho xuất hàng đi):**
- Nhân viên quét các sản phẩm cần lấy.
- Đóng gói các sản phẩm thành Kiện (Ví dụ 10 cái vào 1 thùng). 
- Xác nhận phiếu.

**Tại Bước 2 (Kho nhận hàng về):**
- Nhân viên nhận được Thùng hàng (Kiện).
- Quét mã phiếu Bước 2 để mở phiếu.
- **Cách quét chuẩn:** Quét mã vạch dán trên Kiện hàng (`PACK...`). Ứng dụng sẽ tự động ghi nhận số lượng của TOÀN BỘ sản phẩm trong kiện. (VD: Kiện chứa 10 cái -> Quét 1 phát đạt 10/10).
- ⚠️ **Lưu ý ở Bước 2:**
  - Tuyệt đối không được quét thêm sản phẩm lạ (Không có ở bước 1) vào phiếu Bước 2. Hệ thống đã khoá tính năng này để bảo mật.
  - Số lượng hàng rời (nếu có) bị khoá giới hạn chặt chẽ bằng đúng số lượng rời gửi từ Bước 1. Quét dư sẽ báo lỗi ngay lập tức.

---

## 5. Các tính năng và phím tắt khác

- ⌨️ **Sửa số lượng tay (Numpad):** Nếu số lượng quá nhiều (VD: 500 cái), không cần quét 500 lần. Bạn chỉ cần nhấn thẳng vào dòng sản phẩm trên màn hình, một bàn phím số sẽ hiện ra. Bạn nhập số "500" và nhấn OK.
- 🧹 **Làm lại (Clear):** Biểu tượng cây chổi quét. Dùng khi bạn lỡ quét sai linh tinh và muốn xoá số lượng về 0 để quét lại từ đầu. Tính năng này rất an toàn, không làm hỏng cấu trúc kiện hàng của bạn.
- 🗂️ **Quyền truy cập (Security):** Nếu bạn không được phân quyền "Sửa" tại một kho cụ thể, bạn có thể nhìn thấy phiếu nhưng khi quét mã, hệ thống sẽ từ chối và báo "Bạn không có quyền chỉnh sửa".

---

**Cần Hỗ Trợ Kỹ Thuật?**
Nếu gặp sự cố, vui lòng chụp màn hình thông báo lỗi (chữ đỏ) và gửi cho Quản trị viên hệ thống để được xử lý nhanh nhất!
