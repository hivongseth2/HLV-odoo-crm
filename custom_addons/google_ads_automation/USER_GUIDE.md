# Cẩm Nang Vận Hành Chi Tiết: Google Ads Automation (Odoo 18)

Tài liệu này hướng dẫn bạn cách sử dụng từng tính năng trong hệ thống để quản lý quảng cáo dựa trên dữ liệu tồn kho và doanh thu thực tế.

![Thanh Menu Hệ Thống](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775200150112.png)

---

## 1. Menu: Danh Mục Sản Phẩm (Product Feed)
Đây là nơi bạn chọn những sản phẩm nào trong Odoo sẽ được tham gia vào guồng quay quảng cáo.

![Giao Diện Danh Sách Product Feed](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775200200231.png)

### Bước 1: Thêm sản phẩm
1.  Nhấn **Mới** (New).
2.  Chọn **Tài Khoản Google Ads** bạn muốn liên kết cho nhóm sản phẩm này.
3.  Nhấn nút **"Thêm Sản Phẩm"**: Odoo sẽ tự động liệt kê các sản phẩm thuộc danh mục bạn chọn vào danh sách bên dưới.

![Giao Diện Tạo Mới Product Feed](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775201803222.png)

### Bước 2: Theo dõi chỉ số tồn kho thực tế
Sau khi đã có dữ liệu, bạn sẽ thấy biểu đồ phân bổ tồn kho trực quan.

![Biểu Đồ Trạng Thái Tồn Kho](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775202180216.png)

*   **Tồn kho**: Số lượng khả dụng trong kho Odoo.
*   **TB Bán/Ngày**: Tốc độ bán hàng trung bình (Odoo tự tính dựa trên đơn hàng 30 ngày qua).
*   **Số ngày tồn**: Dự báo thời gian còn hàng.
*   **Trạng thái (Màu sắc)**:
    *   🔴 **Critical**: Sắp cháy hàng -> Hệ thống sẽ ưu tiên tắt QC.
    *   🟡 **Low**: Hàng sắp hết -> Cân nhắc giảm thầu.
    *   🟢 **Healthy**: Hàng dồi dào -> Sẵn sàng tăng ngân sách.

![Danh Sách Chi Tiết Sản Phẩm Kèm Chỉ Số](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775202181999.png)

---

## 2. Menu: Chiến Lược Tự Động (Automation Strategies)
Nơi bạn thiết lập "Luật chơi" cho hệ thống tự động hóa.

![Giao Diện Các Chiến Lược Đang Chạy](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775202326014.png)

### Các loại chiến lược có sẵn:
1.  **Bảo vệ hàng sắp hết (Inventory Protection)**: Ưu tiên bảo vệ kho. Nếu hàng dưới mức X, tự động Pause quảng cáo.
2.  **Tùy chỉnh (Custom Strategy)**: Bạn tự định nghĩa luật dựa trên các mẫu cấu hình chung.

![Chọn Loại Chiến Lược](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775202500627.png)

### Cấu hình chi tiết:
Người dùng có thể tự định nghĩa điều kiện lọc (Ví dụ: "Chi phí > 0") và hành động tương ứng (Ví dụ: "Chỉ thông báo").

![Cấu Hình Quy Tắc Tùy Chỉnh](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775204235222.png)

---

### Cấu hình thông minh:
Với các chiến lược mẫu (Template), bạn có thể thiết lập các ngưỡng (Thresholds) để hệ thống tự ra quyết định:
*   **Ngưỡng tồn thấp/cao**: Để kích hoạt hành động Bật/Tắt.
*   **Thay đổi Budget**: Tỷ lệ % tăng/giảm ngân sách tự động.

![Cấu Hình Ngưỡng Và Hiệu Suất](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775202395160.png)

### Cách kích hoạt:
1.  Sau khi chọn chiến lược, nhấn nút **⚡ SINH RULES TỰ ĐỘNG**. 
2.  Odoo sẽ quét danh sách sản phẩm và tạo ra hàng loạt các "Quy tắc" cụ thể trong tab **Danh Sách Rules**.
3.  Nhấn **Kích Hoạt Chiến Lược** để bắt đầu vận hành thực tế.

![Giao Diện Vận Hành Chiến Lược](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775202431738.png)

![Danh Sách Các Quy Tắc Được Sinh Ra](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775202457283.png)

---

## 3. Menu: Chiến Dịch (Campaigns)
Giám sát hiệu quả thực tế của từng chiến dịch quảng cáo.

![Danh Sách Chiến Dịch Kèm Hiệu Suất Google Ads](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775203709896.png)

### Các tính năng chính:
*   **Đồng bộ số liệu (Sync)**: Nhấn nút **"Đồng bộ Google"** để lấy dữ liệu mới nhất về Lượt nhấp, Chi phí, Impressions.
*   **Quản lý trạng thái**: Bật/Tắt chiến dịch ngay từ Odoo. Trạng thái sẽ được cập nhật lên tài khoản Google Ads sau vài giây.

![Tạo Mới Và Đồng Bộ Chiến Dịch](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775203803997.png)

### Dashboard hiệu quả (ROAS/CPA):
Trong mỗi chiến dịch, bạn sẽ thấy Dashboard thống kê 4 chỉ số vàng:
1.  **CLICKS**: Tổng lượt khách truy cập vào web.
2.  **VIEWS**: Số lần quảng cáo hiển thị.
3.  **SPEND**: Số tiền thực tế đã tiêu (VNĐ).
4.  **ORDERS**: Số đơn hàng thực tế chuyển đổi thành công trong Odoo.

![Dashboard Thống Kê Hiệu Quả Chiến Dịch](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775203854822.png)

*   **Danh Sách Sản Phẩm Trong Chiến Dịch**: Odoo tự động liệt kê các sản phẩm thuộc chiến dịch này kèm trạng thái tồn kho hiện thời (Tồn Cao/Tồn Thấp) để bạn điều chỉnh ngân sách cho phù hợp.

---

## 4. Menu: Nhóm Quảng Cáo (Ad Groups)
Quản lý chi tiết từng nhóm mục tiêu trong chiến dịch một cách có hệ thống.

![Danh Sách Nhóm Quảng Cáo Theo Từng Chiến Dịch](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775204259446.png)

### Quy trình tạo và cấu hình:
1.  **Tạo mới**: Nhấn nút **Mới**, nhập tên nhóm và chọn **Chiến dịch** cha.
2.  **Phân loại (Ad Group Type)**: 
    *   `Standard`: Quảng cáo tìm kiếm thông thường.
    *   `Display`: Quảng cáo hiển thị hình ảnh.
    *   `Discovery`: Quảng cáo khám phá.
    *   `Shopping`: Quảng cáo mua sắm sản phẩm.
3.  **Đồng bộ**: Nhấn **Đồng bộ lên Google** để tạo nhóm thực tế trên tài khoản Ads.

![Thiết Lập Thông Tin Kỹ Thuật Cho Nhóm](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775204314831.png)

### Phân tích hiệu suất nhóm:
Odoo cung cấp hệ thống phân tích sâu giúp bạn biết nhóm sản phẩm nào đang hoạt động tốt nhất:
*   **Phân tích Hiệu suất Nhóm**: Tự động tính toán **Tỷ lệ ra đơn** và **ROAS nhóm**.
*   **Thống kê chi tiết**: Clicks, Impressions, Conversions, Cost được trình bày trực quan bằng Icon ở chân trang.
*   **Liên kết Sản phẩm**: Bạn có thể gắn tag các sản phẩm cụ thể thuộc về nhóm quảng cáo này để Odoo theo dõi sát sao tồn kho của chúng.

![Báo Cáo Hiệu Suất Và Dashboard Nhóm](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775204338046.png)

### Quản lý vận hành:
*   **Trạng thái Live**: Theo dõi xem nhóm đang "Đang hoạt động" hay "Tạm dừng".
*   **Thao tác nhanh**: Bạn có thể **Tạm dừng trên Google** hoặc **Xóa khỏi Google Ads** ngay lập tức nếu nhóm không đạt hiệu quả mong muốn.

![Quản Lý Trạng Thái Và Sản Phẩm Trong Nhóm](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775204361035.png)

---

## 5. Menu: Mẫu Quảng Cáo (Ads)
Nơi quan trọng nhất để tạo nội dung hiển thị tới khách hàng.

![Danh Sách Mẫu Quảng Cáo Kèm Trạng Thái](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775204703780.png)

### Soạn thảo nội dung (RSA/RDA):
*   **Tiêu đề (Headlines)**: Nhập ít nhất 3 dòng. Mỗi dòng 1 ý tưởng khác nhau.
*   **Mô tả (Descriptions)**: Nhập ít nhất 2 dòng mô tả chi tiết sản phẩm.
*   **Đường dẫn (Final URL)**: Trang web mà khách sẽ đến khi bấm vào quảng cáo.

### Tính năng Tự Sửa Lỗi (Auto-Fix):
*   Nếu bạn soạn mẫu quảng cáo không đúng chuẩn (ví dụ: Soạn mô tả cho quảng cáo Tìm kiếm nhưng chiến dịch lại là YouTube), Odoo sẽ **tự động chuyển đổi định dạng** sang loại tương thích nhất. Bạn chỉ cần nhấn **"Cập nhật nội dung"**, hệ thống sẽ lo phần còn lại.

### Theo dõi tương tác thực tế:
Odoo hiển thị phân tích tương tác ngay trên Form mẫu quảng cáo:
*   **Tỷ lệ ra đơn/ROAS dự tính**: Dự báo hiệu quả của riêng nội dung quảng cáo này.
*   **Auto-sync Active**: Dữ liệu được đồng bộ liên tục 2 chiều với Google Ads.
*   **Preview nội dung**: Bạn có thể xem lại chính xác các Headlines/Descriptions nào đang được chạy.

![Chi Tiết Nội Dung Và Phân Tích Tương Tác Mẫu Quảng Cáo](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775204706175.png)

---

## 6. Menu: Quy Tắc Tự Động (Automatic Rules)
Đây là "bộ não" thực thi của hệ thống, nơi tập hợp tất cả các lệnh điều khiển quảng cáo dựa trên dữ liệu thời gian thực.

![Quản Lý Quy Tắc Tập Trung Theo Nhóm Hành Động](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775204906462.png)

### Cấu trúc một Quy tắc:
Mỗi quy tắc hoạt động theo logic **IF (Nếu)** -> **THEN (Thì)**:
*   **IF (Điều kiện)**: Bạn chọn trường dữ liệu để theo dõi (Ví dụ: Tồn kho thực tế, CPA, Clicks...).
*   **Toán tử**: Lớn hơn, Nhỏ hơn, Bằng...
*   **THEN (Hành động)**: 
    *   `Tạm dừng (Pause)`: Tắt quảng cáo ngay lập tức.
    *   `Bật lại (Enable)`: Mở lại quảng cáo khi điều kiện cho phép.
    *   `Chỉ thông báo`: Gửi tin nhắn vào Chatter để bạn tự xử lý.

![Giao Diện Thiết Lập Logic IF-THEN Trực Quan](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775204908140.png)

### Giám sát và Nhật ký (Logs):
Đây là phần quan trọng nhất để bạn kiểm soát hệ thống tự động:
*   **Lịch sử thực thi**: Hệ thống lưu lại danh sách tất cả các lượt chạy để bạn đối soát.
*   **Chi tiết từng lượt chạy**: Nhấp vào một dòng log để xem giải thích chi tiết lý do hệ thống ra quyết định.
    *   Ví dụ: *"Chạy thành công - Không có đối tượng nào thoả mãn điều kiện lúc này"* hoặc *"Đã tạm dừng quảng cáo vì Tồn kho (4.0) thấp hơn ngưỡng (5.0)"*.

![Danh Sách Toàn Bộ Lịch Sử Chạy Quy Tắc](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775205043598.png)

![Chi Tiết Một Lượt Chạy Và Nội Dung Giải Thích](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775205037953.png)

---

## 7. Menu: Lượt Chuyển Đổi (Conversions)
Theo dõi từng đơn hàng thực tế phát sinh từ quảng cáo Google. Đây là dữ liệu quan trọng nhất để đánh giá hiệu quả kinh doanh.

![Danh Sách Các Đơn Hàng Thành Công Từ Google Ads](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775205150940.png)

### Các thông tin đo lường chính:
*   **Mã GCLID (Google Click ID)**: Mã định danh click duy nhất từ Google. Nếu đơn hàng có mã này, Odoo sẽ tự động liên kết để đo lường.
*   **Doanh thu thực tế**: Số tiền khách đã thanh toán cho đơn hàng.
*   **Trạng thái đơn hàng**: Đồng bộ thời gian thực với module Bán hàng (Đang xử lý, Hoàn thành, Đã hủy).
*   **Phân tích Attribution**: Xem đơn hàng này thuộc về chiến dịch nào và chi phí quảng cáo đã bỏ ra cho click đó là bao nhiêu.

### Tính năng Offline Conversion (Upload API):
Hệ thống hỗ trợ gửi dữ liệu "ngược" về cho Google Ads để thuật toán AI của Google học hỏi và tối ưu đúng tệp khách hàng hơn:
*   **Tự động Upload**: Khi đơn hàng chuyển trạng thái "Hoàn thành", Odoo sẽ tự động đẩy doanh thu về Google qua API (Nếu bạn cấu hình loại `Upload Clicks`).
*   **ROAS Đơn hàng**: Tính toán ngay tại chỗ: *"Với click này bạn bỏ ra 500đ và thu về 1.500.000đ"*.

![Chi Tiết Một Lượt Chuyển Đổi Và Thông Tin Attribution](file:///C:/Users/atu30/.gemini/antigravity/brain/8926f9b8-0514-4c41-9059-ed35ae7f66a3/artifacts/media__1775205152954.png)

---

## 8. Menu: Cấu Hình Tag (Tag Config)
Dành cho việc cài đặt theo dõi lên Website.

1.  Nhập mã GTM hoặc mã Google Ads của bạn.
2.  Odoo tự động sinh ra các **đoạn mã PHP/JS (Snippets)** phía dưới.
3.  Bạn chỉ việc Copy các đoạn mã này và dán vào Website (WooCommerce/WordPress) theo hướng dẫn đi kèm.
4.  **Báo cáo GA4**: Kết nối GA4 để xem biểu đồ mật độ sự kiện (Mua hàng, Thêm giỏ hàng...) ngay trên Odoo để biết thẻ theo dõi có đang hoạt động tốt không.

