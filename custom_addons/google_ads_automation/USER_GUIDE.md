# Hướng Dẫn Sử Dụng Module Google Ads Automation

Module này giúp tự động hóa việc bật/tắt và tối ưu ngân sách quảng cáo Google Ads dựa trên dữ liệu thực tế từ Odoo (Tồn kho, Lợi nhuận, Tốc độ bán hàng).

---

## 🏗 Bước 1: Kết nối tài khoản Google Ads

Để Odoo có thể "nói chuyện" được với Google Ads, bạn cần cấu hình thông tin API.

1. Truy cập: **Google Ads > Cấu Hình > Tài Khoản API**.
2. Nhấn **Mới** và điền các thông tin kỹ thuật (Lấy từ Google Cloud Console & Google Ads Manager):
   - **Developer Token**
   - **Client ID & Client Secret**
   - **Refresh Token**
   - **Operating Customer ID**: ID tài khoản quảng cáo (VD: 123-456-7890, viết liền 1234567890).
3. Nhấn **Kiểm tra kết nối**. Nếu hiện thông báo "Thành công" và trạng thái chuyển sang **Đã Kết Nối** là xong.
4. Nhấn **Đồng bộ toàn bộ dữ liệu** để lấy danh sách Chiến dịch (Campaigns) hiện có về Odoo.

---

## 📦 Bước 2: Thiết lập Product Feed (Nạp hàng)

Đây là nơi bạn cho hệ thống biết sản phẩm nào trong Odoo đang chạy trong chiến dịch nào trên Google.

1. Truy cập: **Google Ads > Product Feed**.
2. Tạo mới một Feed (VD: "Feed Giày Nam"). Chọn tài khoản vừa kết nối.
3. Nhấn **Thêm Sản Phẩm**:
   - Bạn có thể chọn thủ công từng mã hoặc thêm cả danh mục sản phẩm (Category).
   - Hệ thống sẽ tự động quét: Tồn kho thực tế, Giá vốn, Giá bán, tính toán % Biên lợi nhuận.
4. **Liên kết Chiến dịch**: 
   - Tại mỗi dòng sản phẩm, nhấn vào cột **Chiến Dịch Liên Kết** để chọn các chiến dịch Google Ads đang chạy cho sản phẩm đó.
   - *Lưu ý: Một sản phẩm có thể chạy nhiều chiến dịch (VD: Search, PMax, Remarketing).*

---

## 🧠 Bước 3: Cấu hình Chiến Lược (Strategy)

Thay vì phải tự viết từng quy tắc phức tạp, bạn chỉ cần chọn chiến lược có sẵn.

1. Truy cập: **Google Ads > Chiến Lược Tự Động**.
2. Tạo chiến lược mới và chọn loại phù hợp:
   - **Bảo vệ hàng sắp hết**: Tự động tắt quảng cáo khi kho sắp cạn để tránh phí click lãng phí.
   - **Đẩy hàng tồn kho cao**: Tăng ngân sách cho các mã hàng đang tồn đọng quá lâu.
   - **Tối ưu lợi nhuận**: Tắt các chiến dịch có CPA (chi phí/đơn) quá cao so với biên lợi nhuận sản phẩm.
   - **Cân bằng tự động**: Kết hợp tất cả các logic trên.
3. Cấu hình các **Ngưỡng (Threshold)**:
   - VD: Thế nào là tồn thấp? (Dưới 10 cái), Biên lợi nhuận tối thiểu là bao nhiêu? (15%).
4. Nhấn **Sinh Rules Tự Động**: Hệ thống sẽ tự tạo ra hàng loạt quy tắc cụ thể cho từng sản phẩm trong Feed.

---

## ⚡ Bước 4: Chế độ Chạy & Thực thi

1. **Chế độ Review (Mặc định)**:
   - Nút **Live** đang TẮT.
   - Hệ thống vẫn chạy, vẫn đánh giá quy tắc, nhưng **CHỈ GHI LOG** và thông báo, không tác động thật lên Google Ads.
   - Xem kết quả tại: **Google Ads > Lịch Sử Quy Tắc**.
2. **Chế độ Live (Tự động thật)**:
   - Sau khi kiểm tra Log thấy hệ thống tính toán đúng ý mình, hãy bật nút **Live** trên Chiến lược.
   - Lúc này, khi kho hết hoặc CPA quá cao, Odoo sẽ gửi lệnh **Pause** trực tiếp lên tài khoản Google Ads của bạn.

---

## ⏰ Cơ chế vận hành tự động

Hệ thống đã được cài đặt lịch trình chạy ngầm (Cron job) hàng ngày:
1. **0h sáng**: Sync dữ liệu hiệu quả (Clicks, Cost, Conversions) từ Google Ads của ngày hôm trước.
2. **0h15 sáng**: Cập nhật tồn kho thực tế và tốc độ bán hàng từ kho Odoo.
3. **0h30 sáng**: Đánh giá tất cả quy tắc và thực thi hành động (Bật/Tắt/Tăng giảm ngân sách).

---

## 🎯 Lưu ý quan trọng để đạt hiệu quả cao

1. **Đồng bộ đơn hàng**: Đảm bảo đơn hàng từ WordPress/WooCommerce được sync về Odoo đều đặn để hệ thống tính "Số ngày tồn kho còn lại" chính xác.
2. **Tracking Conversion**: Bạn **bắt buộc** phải cài Google Tag (gtag.js) trên WordPress để Google Ads đo được đơn hàng. Nếu Google Ads không có dữ liệu đơn hàng (Conversion = 0), module sẽ hiểu lầm là quảng cáo không hiệu quả và tắt nó đi.
3. **Product Mapping**: Một sản phẩm Odoo nên được map chính xác vào Campaign quảng cáo của chính nó. Nếu map sai, hệ thống sẽ tắt nhầm chiến dịch của sản phẩm khác.
