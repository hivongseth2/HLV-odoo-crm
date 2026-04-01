# Kịch Bản Kiểm Thử (Test Cases) Tổng Quát - Google Ads Automation

Tài liệu này cung cấp các kịch bản kiểm thử chuẩn hóa cho hệ thống. Các cụm từ trong ngoặc vuông `[...]` đại diện cho dữ liệu tùy ý (Sản phẩm, Chiến dịch, Tài khoản) của người dùng.

---

## 1. PHÂN HỆ PRODUCT FEED (NGUỒN CẤP SẢN PHẨM)

| ID | Tên Kịch Bản | Tiền Điều Kiện | Các Bước Thực Hiện | Kết Quả Mong Đợi | Kết Quả Thực Tế |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **PF_01** | Khởi tạo Dashboard Feed | User có quyền Quản lý. | 1. Tạo Feed mới, chọn một [Tài khoản Ads].<br>2. Lưu lại. Xem Dashboard ở Header. | Feed tạo thành công. Thanh trạng thái ban đầu mặc định là 100% xanh lá (Healthy). | |
| **PF_02** | Thêm Sản phẩm thủ công | Có sẵn [Sản phẩm A] trong kho Odoo có mã [SKU A]. | 1. Tại tab Chi tiết Feed, chọn [Sản phẩm A] và lưu. | Cột Tên hiển thị đúng định dạng: `[[SKU A]] [Tên Sản phẩm A]`. | |
| **PF_03** | Tự động móc nối (Auto Link) | Trên Google Ads có Chiến dịch chứa từ khóa của [SKU A]. | 1. Nhấn nút `Auto Link Campaigns`. | Hệ thống tìm thấy mã [SKU A] và tự động điền Chiến dịch tương ứng vào cột liên kết. | |
| **PF_04** | Xử lý khi không tìm thấy mã | [Sản phẩm B] có mã [SKU B] không khớp với bất kỳ Chiến dịch nào. | 1. Nhấn nút `Auto Link Campaigns`. | Dòng sản phẩm này giữ nguyên, không bị map sai. Hiển thị thông báo (Warning) nếu không có gì thay đổi. | |
| **PF_05** | Tính toán Giá trị & Lợi nhuận | [Sản phẩm A] có Giá vốn, Giá bán và Tồn kho cụ thể. | 1. Nhấn nút `Làm Mới Tồn Kho`. | - Tồn kho thực tế cập nhật đúng số Odoo.<br>- Biên LN (%) tính đúng công thức: `(Bán - Vốn) / Bán`. | |
| **PF_06** | Xử lý tốc độ bán hàng | Đã phát sinh đơn hàng (Done) cho [Sản phẩm A] trong 30 ngày qua. | 1. Cập nhật tồn kho. | - TB Bán/ngày = [Tổng bán 30 ngày] / 30.<br>- Số Ngày Tồn = [Tồn hiện tại] / [TB Bán/ngày]. | |
| **PF_07** | Cảnh báo trạng thái kho | Hạ tồn kho [Sản phẩm A] xuống mức 0 hoặc dưới ngưỡng tối thiểu. | 1. Cập nhật tồn kho. | Cột trạng thái tự động chuyển sang màu Đỏ (`Cảnh báo/Sắp hết hàng`). | |

---

## 2. PHÂN HỆ CHIẾN LƯỢC TỰ ĐỘNG (STRATEGY ENGINE)

| ID | Tên Kịch Bản | Tiền Điều Kiện | Các Bước Thực Hiện | Kết Quả Mong Đợi | Kết Quả Thực Tế |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **ST_01** | Chiến lược Bảo vệ kho (Protect Low) | [Sản phẩm A] sắp hết hàng và đã được nối với [Chiến dịch X]. | 1. Chọn mẫu `Bảo vệ hàng sắp hết`.<br>2. Nhấn `Sinh Rules`. | Tự động tạo Rule: "Nếu Tồn kho < [Ngưỡng] thì Tạm dừng [Chiến dịch X]". | |
| **ST_02** | Kiểm tra ràng buộc liên kết | Có sản phẩm trong Feed nhưng chưa được nối với Chiến dịch nào. | 1. Nhấn `Sinh Rules`. | Hệ thống báo lỗi (UserError) yêu cầu người dùng map sản phẩm trước khi tạo luật tự động. | |
| **ST_03** | Cơ chế làm mới luật (Refresh) | Chiến lược đã có sẵn các Rules tự động từ trước. | 1. Nhấn lại nút `Sinh Rules`. | Các Rules tự động cũ bị xóa, Rules mới được tạo lại dựa trên dữ liệu hiện tại. Rules tạo thủ công được giữ nguyên. | |
| **ST_04** | Kích hoạt hàng loạt (Mass Activate) | Chiến lược và các Rules đang ở trạng thái Nháp. | 1. Nhấn nút `Kích hoạt` trên Chiến lược. | Trạng thái Chiến dịch chuyển sang "Đang chạy" và TẤT CẢ Rule con tự động được bật (Active). | |
| **ST_05** | Chiến lược Tùy chỉnh (Custom) | Người dùng chọn mẫu `Tùy Chỉnh`. | 1. Cấu hình Điều kiện và Hành động bất kỳ.<br>2. Nhấn `Sinh Rules`. | Hệ thống nhân bản đúng cấu hình người dùng vừa nhập cho tất cả sản phẩm trong danh sách. | |

---

## 3. PHÂN HỆ QUY TẮC & THỰC THI (RULES & EXECUTION)

| ID | Tên Kịch Bản | Tiền Điều Kiện | Các Bước Thực Hiện | Kết Quả Mong Đợi | Kết Quả Thực Tế |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **RL_01** | Chế độ chạy thử (Dry-run) | Chế độ `LIVE` đang TẮT. Rule thỏa mãn điều kiện Tạm dừng. | 1. Nhấn `Chạy Thử Ngay`. | Không có thay đổi trên Google Ads. Nhật ký (Log) ghi lại trạng thái: `[DRY-RUN] Hành động Pause`. | |
| **RL_02** | Chế độ thực thi thật (Live Mode) | Chế độ `LIVE` đang BẬT. Rule thỏa mãn điều kiện. | 1. Nhấn `Chạy Thử Ngay`. | [Chiến dịch] trên Google Ads bị thay đổi trạng thái ngay lập tức. Nhật ký ghi: `Action Taken`. | |
| **RL_03** | Thực thi theo lịch (Cron Job) | Cron Job `Google Ads: Đánh giá quy tắc` đã được bật. | 1. Chờ đến giờ chạy hoặc nhấn `Run Manually` trong cài đặt Cron. | Hệ thống tự động thực hiện: Đồng bộ số liệu -> Cập nhật kho -> Đánh giá toàn bộ Rules. | |

---

## 4. CHIẾN DỊCH & QUẢNG CÁO (CAMPAIGNS & ADS)

| ID | Tên Kịch Bản | Tiền Điều Kiện | Các Bước Thực Hiện | Kết Quả Mong Đợi | Kết Quả Thực Tế |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **CP_01** | Ràng buộc tạo mới (Validation) | Tạo Chiến dịch PMax nhưng không có Logo hoặc Merchant ID. | 1. Nhấn `Đồng bộ lên Google`. | Hệ thống chặn lại và báo lỗi thiếu thông tin bắt buộc dành riêng cho loại chiến dịch này. | |
| **CP_02** | Đồng bộ Demo (Demo Account) | Tài khoản đang ở `Chế độ Demo`. | 1. Nhấn `Đồng bộ`. | Hệ thống giả lập quá trình thành công, cấp ID ảo và không gửi yêu cầu thực tế ra ngoài Internet. | |
| **AD_01** | Quảng cáo mẫu (RSA) | Nhập nội dung quảng cáo Search Thích ứng. | 1. Nhập ít hơn 3 tiêu đề. Nhấn Đồng bộ. | Hệ thống báo lỗi yêu cầu tối thiểu 3 tiêu đề và 2 mô tả theo quy định của Google. | |
| **AD_02** | Xử lý địa chỉ URL | Nhập URL không có tiền tố `https://`. | 1. Nhấn Lưu hoặc Đồng bộ. | Odoo tự động chuẩn hóa bằng cách thêm tiền tố an toàn vào URL. | |

---

## 5. TRỢ LÝ AI (ADSROID AI)

| ID | Tên Kịch Bản | Tiền Điều Kiện | Các Bước Thực Hiện | Kết Quả Mong Đợi | Kết Quả Thực Tế |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **AI_01** | Phân tích thủ công | Chiến dịch đã có dữ liệu hiệu quả (Clicks/Cost). | 1. Nhấn `Hỏi Nhận Định AI`. | Sau vài giây, hệ thống hiển thị bảng phân tích và lời khuyên tối ưu dựa trên số liệu thực. | |
| **AI_02** | Tự động áp dụng (Auto Apply) | Cấu hình tài khoản cho phép AI tự động thực thi. | 1. Kích hoạt phân tích AI. | Nếu AI đề xuất Tạm dừng, Odoo sẽ tự động thực hiện lệnh Mutate API ngay lập tức. | |

---
**Hướng dẫn thực hiện:**
- Đối với mỗi bước kiểm thử, hãy thay thế các giá trị trong ngoặc `[...]` bằng dữ liệu thật trong môi trường test của bạn.
- Đánh dấu **Pass** nếu kết quả khớp với mong đợi, ngược lại ghi chú lỗi chi tiết.
