# Cẩm Nang Vận Hành: Tự Động Hóa Google Ads (Odoo 18)

Chào mừng bạn đến với hệ thống điều khiển Google Ads thông minh. Tài liệu này tập trung vào các thao tác nghiệp vụ hàng ngày để giúp bạn tối ưu hóa doanh thu và bảo vệ ngân sách một cách tự động.

---

## 1. Quản Lý Danh Mục Sản Phẩm Quảng Cáo (Product Feed)

Đây là "Trái tim" của hệ thống, nơi kết nối lượng tồn kho thực tế trong Odoo với các chiến dịch trên Google Ads.

### Thêm sản phẩm vào hệ thống
1. Vào menu **Google Ads > Product Feed (Danh mục sản phẩm)**.
2. Chọn bản ghi sẵn có hoặc nhấn **Mới**.
3. Nhấn nút **Thêm tất cả từ danh mục** để lọc và đưa các dòng sản phẩm bạn muốn chạy quảng cáo vào danh sách.

### Đọc hiểu các cột số liệu (Nghiệp vụ kho)
Hệ thống tự động tính toán các chỉ số quan trọng sau:
- **Tồn kho thực tế**: Số lượng khả dụng trong kho Odoo hiện tại.
- **TB Bán/Ngày**: Tốc độ bán hàng trung bình trong 30 ngày gần nhất.
- **Số ngày tồn**: Dự báo bao nhiêu ngày nữa bạn sẽ cháy hàng (`Tồn kho / TB bán`).
- **Trạng thái (Màu sắc)**: 
    - 🔴 **Kịch khung (Critical)**: Cần dừng quảng cáo ngay lập tức để tránh khách đặt hàng mà không có giao.
    - 🟡 **Sắp hết (Low)**: Cần cân nhắc giảm ngân sách hoặc nhập thêm hàng.
    - 🟢 **An toàn (Healthy)**: Có thể tăng ngân sách quảng cáo để đẩy mạnh doanh số.

> [!TIP]
> **Giao diện trực quan**: Hãy chụp ảnh danh sách sản phẩm với các cột màu sắc sinh động để làm hướng dẫn.
> ![Giao diện Product Feed](img/huong_dan_feed.png)

---

## 2. Thiết Lập Chiến Lược Tự Động (Bộ Máy Điều Khiển)

Thay vì phải bật/tắt thủ công cho hàng trăm sản phẩm, bạn chỉ cần chọn một "Chiến lược" và Odoo sẽ tự động thực hiện cho bạn.

### Các loại chiến lược cốt lõi:
1.  **Bảo vệ hàng sắp hết**: Hệ thống sẽ tự động "Pause" quảng cáo khi kho chạm mốc tối thiểu bạn đặt ra.
2.  **Đẩy hàng tồn cao**: Ưu tiên ngân sách cho các mặt hàng đang "ôm kho" quá nhiều để giải phóng vốn.
3.  **Tối ưu lợi nhuận**: Tự động tắt các mẫu quảng cáo có chi phí quá cao mà không mang lại đơn hàng (dựa trên chỉ số CPA/ROAS).
4.  **Đẩy hàng mới**: Thích hợp cho các bộ sưu tập vừa nhập kho, cần tăng độ phủ ngay lập tức.

### Chiến lược Tùy Chỉnh (Custom) - Mới:
Bạn có thể tự định nghĩa luật chơi riêng bằng cách điền vào tab **Cấu Hình Tùy Chỉnh**:
- **Điều kiện**: Chọn (Chi phí, Lượt nhấp, Lượt hiển thị, Tồn kho...).
- **Hành động**: Chọn (Bật, Tạm dừng, Tăng/Giảm ngân sách).
- **Ví dụ**: "Nếu Lượt nhấp > 200 mà chưa có đơn hàng -> Tạm dừng".

**Cách kích hoạt:** Sau khi cấu hình xong, nhấn nút **⚡ Sinh Rules Tự Động**. Odoo sẽ quét toàn bộ danh mục sản phẩm và tạo ra các câu lệnh (Rules) chi tiết cho từng cái.

> [!IMPORTANT]
> **Chế độ LIVE**: Khi mới thiết lập, hãy để ở chế độ **Dry-Run** để xem hệ thống dự định làm gì. Khi đã tin tưởng, hãy gạt sang **LIVE (Màu đỏ)** để lệnh thực thi thật lên Google.

---

## 3. Dashboard Hiệu Quả & Trợ Lý AI Adsroid

Giao diện Dashboard giúp bạn xem nhanh "sức khỏe" của các chiến dịch mà không cần mở tài khoản Google Ads phức tạp.

### Đọc dải thẻ Dashboard 4 màu:
- **Xanh Dương (Lượt nhấp)**: Khách hàng có quan tâm đến mẫu quảng cáo của bạn không?
- **Đỏ (Chi phí)**: Bạn đã tiêu hết bao nhiêu tiền?
- **Xanh Lá (Đơn hàng)**: Quảng cáo có thực sự mang về doanh thu không?
- **Vàng (Tỷ lệ chốt)**: Hiệu suất của trang bán hàng/nội dung quảng cáo.

### Ra quyết định cùng AI Adsroid:
Tại mỗi Chiến dịch hoặc Sản phẩm, bạn có nút **Hỏi Nhận Định AI**.
1. AI sẽ phân tích dữ liệu 3 chiều: **Quảng cáo (Ads) + Tồn kho (Odoo) + Thị trường**.
2. AI đưa ra chấm điểm hiệu quả và lời khuyên: "Chi phí đang quá cao so với tỷ lệ tồn kho, khuyên bạn nên giảm 20% ngân sách".
3. **Bật Tự Động Áp Dụng**: Nếu bạn quá bận, hãy bật tính năng này để Odoo tự động thực hiện lệnh mà AI đề xuất ngay lập tức.

---

## 4. Tạo Mẫu Quảng Cáo Chuyên Nghiệp (RSA)

Để quảng cáo của bạn được Google ưu tiên hiển thị và có điểm chất lượng cao, hệ thống yêu cầu bạn nhập liệu theo chuẩn **Tìm kiếm thích ứng (RSA)**.

**Quy trình nhập liệu:**
1. Tại mỗi mẫu quảng cáo, tìm trường **Danh sách Tiêu đề**.
2. **Bắt buộc**: Nhập ít nhất **3 dòng** tiêu đề khác nhau (Mỗi tiêu đề 1 dòng).
3. Tại trường **Danh sách Mô tả**: Nhập ít nhất **2 dòng**.
4. Hệ thống sẽ tự động ghép dẻo các dòng này để tạo ra hàng chục biến thể quảng cáo khác nhau cho khách hàng.

> [!TIP]
> **Ví dụ**: 
> - Tiêu đề 1: Giày Sneaker Chính Hãng
> - Tiêu đề 2: Giảm Giá 30% Hôm Nay
> - Tiêu đề 3: Ship Cod Toàn Quốc
> ![Mẫu quảng cáo chuyên nghiệp](img/huong_dan_rsa.png)

---

## 5. Kiểm Soát Nhật Ký Tự Động

Bạn luôn có thể trả lời câu hỏi: *"Tại sao hôm nay quảng cáo này lại bị tắt?"* bằng cách vào **Google Ads > Lịch Sử Quy Tắc**.

- **Thời gian**: Hệ thống vừa quét lúc mấy giờ?
- **Hành động**: Đã Tạm dừng (Paused) hay Đã Bật (Enabled)?
- **Lý do chi tiết**: Giải thích rành mạch dựa trên con số thực tế (VD: Do tồn kho thực tế = 2, thấp hơn mức tối thiểu = 5).

---

## 6. Quy Trình Vận Hành Gợi Ý

1. **Buổi sáng**: Kiểm tra nhanh **Bảng Dashboard** xem có biến động bất thường nào về chi phí không.
2. **Buổi trưa**: Kiểm tra **Lịch Sử Quy Tắc** để xem có bao nhiêu sản phẩm đã bị hệ thống tạm dừng do hết hàng.
3. **Cuối tuần**: Sử dụng **Hỏi Nhận Định AI** cho các chiến dịch lớn để lấy lời khuyên tối ưu ngân sách cho tuần tiếp theo.

---
*Tài liệu dành cho Người vận hành - Hệ thống Google Ads Automation Odoo 18.*
