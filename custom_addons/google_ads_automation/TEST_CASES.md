# Bộ Test Case Chi Tiết - Google Ads Automation

Tài liệu này cung cấp các kịch bản kiểm thử (Test Cases) chi tiết cho từng luồng tính năng của module `google_ads_automation`.

---

## MỤC LỤC
1. [Quản lý Tài Khoản & Chế Độ Demo](#1-quản-lý-tài-khoản--chế-độ-demo)
2. [Quản Lý Chiến Dịch, Nhóm QC, Mẫu QC](#2-quản-lý-chiến-dịch-nhóm-qc-mẫu-qc)
3. [Quản Lý GTM & Tag (Tag Management)](#3-quản-lý-gtm--tag)
4. [Product Feed (Nguồn cấp sản phẩm)](#4-product-feed)
5. [Smart Rule Engine (Chiến Lược Tự Động)](#5-smart-rule-engine-chiến-lược-tự-động)
6. [Thực Thi Rules & Lịch Sử (Mutate & Logs)](#6-thực-thi-rules--lịch-sử)

---

## 1. Quản lý Tài Khoản & Chế Độ Demo

### TC_ACCT_01: Kiểm tra kết nối API thật thành công
- **Mục đích:** Đảm bảo hệ thống xác thực đúng thông tin OAuth2 với Google Ads.
- **Tiền điều kiện:** Có thông tin API Tokens hợp lệ (Client ID, Secret, Developer Token, Refresh Token, Customer ID). Không bật "Demo Mode".
- **Các bước:**
  1. Vào menu `Google Ads > Cấu hình > Tài Khoản`.
  2. Tạo mới Tài khoản, điền đầy đủ các Credentials.
  3. Bấm lưu và bấm nút `Kiểm tra kết nối`.
- **Kết quả mong muốn:**
  - Hệ thống hiển thị thông báo "Kết nối thành công".
  - Trạng thái tài khoản chuyển sang `Đã kết nối`.

### TC_ACCT_02: Cấu hình Tài khoản với Demo Mode
- **Mục đích:** Xác nhận chức năng Test hoạt động độc lập không cần API Google.
- **Tiền điều kiện:** Đang ở form tạo/sửa Tài khoản.
- **Các bước:**
  1. Check vào tuỳ chọn `Chế độ Demo`.
  2. Bấm lưu và bấm nút `Kiểm tra kết nối`.
- **Kết quả mong muốn:**
  - Hệ thống ẩn các trường thông tin Credentials đi.
  - Gắn badge/ribbon "DEMO MODE" để người dùng nhận biết.
  - Thông báo kết nối thành công ngay lập tức và trạng thái đổi thành `Đã kết nối`.

### TC_ACCT_03: Đồng bộ dữ liệu giả lập trong Demo Mode
- **Mục đích:** Chắc chắn rằng hàm Demo Seeder sinh dữ liệu đầy đủ.
- **Tiền điều kiện:** Tài khoản đang bật Demo Mode, trạng thái Đã kết nối.
- **Các bước:**
  1. Trên form Tài khoản, bấm nút `Đồng bộ Dữ liệu` (hoặc `Tải Demo Data` nếu nút riêng).
  2. Vào list view các menu: Chiến Dịch, Nhóm Quảng Cáo, Quảng Cáo, Conversion, GTM Tag.
- **Kết quả mong muốn:**
  - Sinh thành công 4+ Chiến dịch demo (Search, Display, PMax...).
  - Sinh tương ứng Nhóm QC và Mẫu QC.
  - Dữ liệu có chứa các Metrics (Clicks, Cost, Conversions) để hỗ trợ test.

---

## 2. Quản Lý Chiến Dịch, Nhóm QC, Mẫu QC

### TC_CAMP_01: Tạo mới Chiến dịch (Search/Display/Shopping)
- **Mục đích:** Verify form tạo chiến dịch lấy đúng các cấu hình hợp lệ.
- **Tiền điều kiện:** Tài khoản đã nối API/Demo.
- **Các bước:**
  1. Vào `Google Ads > Chiến dịch` -> Bấm `Mới`.
  2. Điền tên chiến dịch, chọn loại (S_ARCH/DISPLAY), Ngân sách hàng ngày, URL đích.
  3. Bấm Lưu và bấm `Đồng bộ lên Google Ads` (nếu có action thủ công).
- **Kết quả mong muốn:**
- **Kết quả mong muốn:**
  - Validations: Báo lỗi nếu thiếu Loại Kênh, Ngân sách hoặc Strategy.
  - Odoo tự handle ẩn field `contains_eu_political_advertising` để bypass rule năm 2025.
  - Lệnh gửi đi thành công (hoặc lưu log giả lập ở Demo). ID Campaign được ghi nhận từ API trả về.

### TC_CAMP_02: Tạo Chiến dịch Tối đa hiệu suất (PMax)
- **Mục đích:** PMax có logic phức tạp đặc thù đòi hỏi upload Logo và Thương hiệu.
- **Tiền điều kiện:** Như TC_CAMP_01.
- **Các bước:**
  1. Tạo chiến dịch mới, chọn loại `PERFORMANCE_MAX`.
  2. Để trống Thương hiệu và Logo PMax -> Lưu và thực thi.
  3. Sửa lại, điền đầy đủ Tên thương hiệu và up file Logo -> Lưu và thực thi.
- **Kết quả mong muốn:**
  - Bước 2: Hiển thị lỗi Validation bắt buộc phải có Logo / Tên thương hiệu.
  - Bước 3: (API thật) Odoo thực hiện transaction nguyên tử: Tạo Asset Logo -> Tạo Asset Text -> Tạo Campaign -> Map Asset. Thành công!

### TC_ADG_01: Ràng buộc Loại Nhóm Quảng Cáo hợp lệ
- **Mục đích:** Tránh lỗi API Google về AdGroupType không khớp Campaign.
- **Tiền điều kiện:** Có sẵn Chiến dịch Tìm kiếm (Search) và Hiển thị (Display).
- **Các bước:**
  1. Tạo `Nhóm Quảng Cáo` mới.
  2. Gắn vào Chiến dịch Search, sau đó ở trường Tùy chọn Loại Nhóm QC chọn `DISPLAY_STANDARD`.
  3. Lưu.
- **Kết quả mong muốn:**
  - Form (onchange) ẩn bớt lựa chọn sai hoặc cảnh báo lỗi/ValidationError nếu cố lưu AdGroupType không cho phép với cấu hình Campaign gốc.

---

## 3. Quản Lý GTM & Tag

### TC_GTM_01: Tự động kéo cấu hình (Sync GTM) qua Readonly API
- **Mục đích:** Kéo cấu hình Workspace, Tags, Triggers từ GTM.
- **Tiền điều kiện:** Tài khoản GTM đã điền Container ID và API Access cho GTM.
- **Các bước:**
  1. Mở menu `Google Ads > Theo dõi chuyển đổi > GTM Tags`.
  2. Bấm nút `Fetch / Đồng bộ Data từ GTM`.
- **Kết quả mong muốn:**
  - Lấy thành công danh sách Tags/Variables hiện có ở Workspace.
  - Các records lưu trong `google.ads.gtm.item` phải là dạng Read-only, user không thể sửa tự do.
  - Nếu là tài khoản Demo, nó tự sinh Data Demo.

### TC_GTM_02: Sinh file script/hook WooCommerce (Code snippet)
- **Mục đích:** Module cung cấp code để gắn vào website vệ tinh.
- **Tiền điều kiện:** Đã tạo bản ghi Cấu hình Tag cơ bản gồm GTM ID / AW-ID.
- **Các bước:**
  1. Kiểm tra tab `Installation Code / Web Snippet` trên form.
- **Kết quả mong muốn:**
  - Cung cấp đủ 3 ô chứa Text Snippet: Head script, Body iframe, và PHP Hook cho WordPress/WooCommerce có chứa GTM ID / AW ID đã điền.

---

## 4. Product Feed

### TC_FEED_01: Cập nhật Tồn kho và Tính toán tự động
- **Mục đích:** Đảm bảo hệ thống gom chính xác thông số cho Sản phẩm.
- **Tiền điều kiện:** Có sẵn một vài `product.template` trong kho, có giá bán (`list_price`), giá vốn (`standard_price`).
- **Các bước:**
  1. Tạo `Product Feed`, chọn Tài khoản và gắn vài sản phẩm vào.
  2. Bấm nút `Cập nhật Tồn kho` hoặc đợi Cron chạy.
  3. Kiểm tra các dòng (lines) của Product Feed.
- **Kết quả mong muốn:**
  - Cột `Tồn Kho Thực Tế` lấy đúng số tồn khả dụng.
  - Cột `Biên lợi nhuận` tình ra đúng `(Giá - Vốn)/Giá * 100`.
  - Cột `Trạng Thái Tồn` đánh giá màu (Sắp hết/Đỏ, Tồn thấp/Vàng, Tồn cao/Xanh dương) khớp với điều kiện cấu hình ngưỡng.

### TC_FEED_02: Map Sản phẩm với Campaign
- **Mục đích:** Gắn sản phẩm tham chiếu để Mutate logic biết pause/enable Campaign nào.
- **Các bước:**
  1. Mở Feed, ấn Edit từng lines, chọn/chỉ định Tên Campaign liên kết.
  2. Chọn thử một campaign không thuộc Tài khoản đang link với Feed.
- **Kết quả mong muốn:**
  - Chỉ cho phép map các Campaign thuộc đúng Account liên kết ở form Feed.
  - Cho phép 1 dòng Sản phẩm map tới > 1 Campaign (VD: Search & PMax).

---

## 5. Smart Rule Engine (Chiến Lược Tự Động)

### TC_RULE_01: Chạy tự sinh Rule cho Chiến Lược "Bảo vệ hàng sắp hết"
- **Mục đích:** Đảm bảo Strategy Engine tạo đủ rules theo template.
- **Tiền điều kiện:** Có Product Feed với Sản phẩm A (Tồn 0 - Sắp hết) đã map Campaign X.
- **Các bước:**
  1. Vào menu `Chiến Lược Tự Động`. Tạo mới, cấu hình loại `Bảo vệ hàng sắp hết`.
  2. Gắn với Tài khoản và Feed vừa tạo.
  3. Bấm nút `Sinh Rules Tự Động`.
  4. Sang tab `Rules Tự Sinh` xem kết quả.
- **Kết quả mong muốn:**
  - Hệ thống sinh ra 1 Rule cho Campaign X với điều kiện: `NẾU tồn kho <= [ngưỡng sắp hết] THÌ Pause Campaign`.

### TC_RULE_02: Đánh giá điều kiện đúng sai trong Rule (Evaluate)
- **Mục đích:** Rule Engine quét dữ liệu và đưa ra True/False chính xác.
- **Tiền điều kiện:** Đã có 1 Rule "NẾU tồn kho < 5 THÌ Pause". SP đang ở mức tồn 10.
- **Các bước:**
  1. Mở form Rule đó, bấm `Chạy Thử Ngay` (Run Once).
  2. Chỉnh tồn kho Product thành 0 (tạo phiếu xuất kho).
  3. Trở lại Odoo, bấm nút `Cập nhật tồn` ở Feed rồi quay lại form Rule bấm `Chạy Thử Ngay`.
- **Kết quả mong muốn:**
  - Lần 1: Log tạo ra với ghi chú `Bình thường (Điều kiện không đạt: 10 >= 5)`. Không Action.
  - Lần 2: Log tạo ra `Đã Xử Lý (0 < 5)`. Hệ thống bắn Action `Pause` cho Campaign.

---

## 6. Thực Thi Rules & Lịch Sử

### TC_EXEC_01: Chế độ Dry-Run (Không Live)
- **Mục đích:** Chế độ Dry-Run phải đảm bảo an toàn, không được Pause/Enable nhầm khi User đang thử nghiệm cấu hình.
- **Tiền điều kiện:** Chiến lược đang TẮT cờ Live. Đã sinh 1 Rule điều kiện đạt mức thực thi.
- **Các bước:**
  1. Bấm `Chạy Thử Ngay` trên Rule (hoặc Cron chạy tổng).
  2. Xem Log hiển thị. Kiểm tra lịch sử tài khoản Google Ads API/Demo.
- **Kết quả mong muốn:**
  - Rule phát hiện cần xử lý (ví dụ: cần Bật Campaign).
  - Log ghi `Đề xuất hành động: Bật Campaign... (Dry-Run: Bỏ qua gọi API thực tế)`.
  - Trạng thái Campaign không bị thay đổi.

### TC_EXEC_02: Chế độ Chạy Thật (Live Mode / Demo Mode)
- **Mục đích:** Các record bắt buộc được ghi và gọi tới Services tương ứng.
- **Tiền điều kiện:** BẬT Live Mode. Tài khoản là Demo Mode (để ko sửa thật trên API). Rule thoả mãn điều kiện Pause.
- **Các bước:**
  1. Run Rule.
  2. Sang mục Chiến dịch xem trạng thái Campaign.
- **Kết quả mong muốn:**
  - Log ghi chú thực thi thành công: `Gọi Mutate API Pause`.
  - Field trạng thái của Campaign trong Odoo tự động chuyển sang `PAUSED`.

### TC_EXEC_03: Báo Cáo Dashboards Metrics
- **Mục đích:** Dữ liệu Clicks/Cost phản ánh mượt mà cho user xem.
- **Tiền điều kiện:** Tài khoản đã có dữ liệu thông qua Đồng bộ.
- **Các bước:**
  1. Mở Cây Danh sách (List/Kanban) Chiến dịch. Xem Dashboard header hoặc Chart (nếu có).
  2. Truy cập form Chiến dịch và Form Nhóm QC xem field Thống kê.
- **Kết quả mong muốn:**
  - Giao diện Dashboard (hoặc fields Kanban/Form) hiển thị đúng tổng chi phí, số click, conversion theo các KPIs.
  - ROI/ROAS được tính tự động mà không bị 0 chia 0 (ZeroDivisionError).

---

## 7. Adsroid AI Integration (Trợ Lý AI)

### TC_AI_01: Xin nhận định từ Adsroid AI (Manual)
- **Mục đích:** Gửi thông số Campaign (Click, Cost, Impression) kết hợp với số liệu Kho hàng (Tồn ròng, Khả dụng, Margin) lên Agent để lấy nhận định.
- **Tiền điều kiện:** Tài khoản đã check cờ `Sử dụng Adsroid AI`, điền đúng API Key và Project ID. Campaign có trạng thái `synced` hoặc đang ở `Demo mode`.
- **Các bước:**
  1. Vào Chiến dịch cụ thể.
  2. Bấm nút `Hỏi Nhận Định Adsroid (AI)`.
- **Kết quả mong muốn:**
  - Hệ thống mất ~3-5s để liên lạc với Supabase Agent.
  - Khối HTML `Adsroid AI Insight` được render hiển thị Điểm đánh giá (Score), Đề xuất (Suggest) và text Insight chi tiết.
  - Một dòng Log lịch sử AI được tạo trong tab `Lịch sử Adsroid`.

### TC_AI_02: Chức năng Auto-Apply của Adsroid
- **Mục đích:** Khi bật tính năng Auto Apply, hệ thống tự động chạy lệnh API (như Pause) nếu AI Insight khuyên làm vậy.
- **Tiền điều kiện:** Trong form Account, Cờ `Tự động áp dụng đề xuất` = Bật.
- **Các bước:**
  1. Giả lập / Sửa Data sao cho Campaign có cost cao nhưng 0 Clicks, Tồn kho SP thì = 0.
  2. Bấm gọi lệnh phân tích Adsroid (Hoặc để Cron Job tự động bắt API).
- **Kết quả mong muốn:**
  - AI trả về Action: `PAUSE`.
  - Hệ thống bắt tín hiệu và **tự động gọi lệnh Mutate Pause Campaign** thay vì đợi con người. Trạng thái Campaign lập tức chuyển sang PAUSED.
