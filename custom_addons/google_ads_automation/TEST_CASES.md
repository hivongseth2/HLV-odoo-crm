# Kịch Bản Kiểm Thử (Test Cases) Chuyên Sâu - Product Feed & Chiến Lược
Tài liệu này tập trung **toàn bộ** vào 2 phân hệ cốt lõi: Nguồn Cấp Sản Phẩm (Product Feed) và Cỗ Máy Sinh Luật Tự Động (Strategy Engine). Bảng đã được thiết kế sẵn cột để kiểm thử viên (Tester) điền kết quả thực tế.

---

## 1. PHÂN HỆ PRODUCT FEED (NGUỒN CẤP SẢN PHẨM)

| ID | Tên Kịch Bản | Tiền Điều Kiện | Các Bước Thực Hiện | Kết Quả Mong Đợi | Kết Quả Thực Tế | Ghi Chú / Bug URL |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **PF_01** | Feed: Tạo mới & View thẻ Dashboard | User có quyền Quản lý. | 1. Tạo Feed mới, chọn một Tài khoản Ads.<br>2. Lưu lại. Trở ra Kanban xem trạng thái. | Feed tạo thành công. Màu sắc thanh tiến độ trên Header Widget ban đầu là 100% xanh lá (Healthy). | | |
| **PF_02** | Line: Thêm 1 dòng SP thủ công | Đang ở form Feed. Có sẵn 1 Sản phẩm `SP_01` trong kho có default_code (SKU) là SKU1. | 1. Bấm thêm dòng, chọn SP_01, lưu. | Cột Tên hiển thị định dạng `[SKU1] Tên SP_01`. | | |
| **PF_03** | Auto Mappings: Tự động móc nối thành công | Trong Account C01 có Campaign tên `Khuyến Mãi Quần Áo SKU1`. | 1. Chọn nút `Auto Link Campaigns`. | Hệ thống tìm thấy text "SKU1" trong tên Campaign và tự động thêm Campaign đó vào cột `Chiến Dịch Liên Kết` của SP_01. Có popup xanh lá. | | |
| **PF_04** | Auto Mappings: Thất bại do không khớp | Dòng `SP_02` mang SKU `SKU_UNMATCH`. Không có Campaign nào chứa text này. | 1. Bấm `Auto Link Campaigns`. | Dòng `SP_02` không được map. Nếu trong toàn bộ Feed không có SP nào được map, hiển thị popup màu vàng (Warning). | | |
| **PF_05** | Math Computation: Cập nhật Tồn Kho (Sale > Cost) | `SP_01` có Giá vốn=100k, Giá Bán=150k. Tồn=10. Chưa bán được đơn nào. | 1. Bấm nút `Làm Mới Tồn Kho`. | - Tồn kho thực tế = 10.<br>- Biên LN (%) = (150-100)/150*100 = 33.33%.<br>- TB Bán/Ngày = 0.<br>- Số Ngày Tồn = vô hạn (cố định số lớn, vd 9999). | | |
| **PF_06** | Math Computation: Tồn kho âm (Cost > Sale) | Cấu hình lộn Giá vốn=200k, Giá Bán=150k. | 1. Cập nhật tồn kho. | Biên LN (%) = -33.33% (Số âm). Hệ thống không lỗi 0 Division. | | |
| **PF_07** | Stock Status: Tự động nhảy Critical | Giảm tồn kho `SP_01` xuống 0 bằng Inventory Adjustment. | 1. Cập nhật tồn kho. | Label cột đánh giá thành: `Sắp Hết Hàng` (Đỏ). | | |
| **PF_08** | Math Computation: TB Bán/Ngày (30D) | Tạo 1 Sale Order đã giao (Done/Delivered) cho `SP_01` với số lượng 60 vào ngày hôm qua. | 1. Cập nhật tồn. | - TB Bán/ngày = 60/30 = 2 cái/ngày.<br>- Số hiệu tồn ngày (Day of Stock) tính lại chính xác. Dựa vào đó nhảy Trạng thái tồn (Low, High, v.v.). | | |

---

## 2. PHÂN HỆ CHIẾN LƯỢC TỰ ĐỘNG (STRATEGY ENGINE)

| ID | Tên Kịch Bản | Tiền Điều Kiện | Các Bước Thực Hiện | Kết Quả Mong Đợi | Kết Quả Thực Tế | Ghi Chú / Bug URL |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **ST_01** | Template 1: Bảo vệ hàng sắp hết (Protect Low) | Feed có `SP_A` đang nợ tồn kho hoặc Tồn=5. SP_A đã map Chiến dịch `CA`. Ngưỡng Tồn Thấp = 20. | 1. Trạng thái Strategy: Nháp.<br>2. Chọn template `Bảo vệ hàng sắp hết`. Bấm `Sinh Rules`. | 1 Rule `[Auto] Pause khi hết hàng — SP_A` sinh ra, Kích hoạt = FALSE (do Strategy đang Nháp). Toán tử `< 20`. Action = Pause. | | |
| **ST_02** | Generate Validation: SP không có campaign liên kết | Feed có SP nhưng KHÔNG map vào Campaign nào. | 1. Bấm `Sinh Rules`. | Odoo báo UserError (Cấm tạo): "Yêu cầu map Sản phẩm vào Campaign trước khi sinh Rule". Màn hình chat log báo màu đỏ lỗi. Không sinh Rule rác. | | |
| **ST_03** | Delete & Re-Generate (Xóa cũ sinh mới) | Strategy đang có sẵn 3 Rules auto. | 1. Bấm lại nút `Sinh Rules`. | Tổng số rule trong tab không đổi (3 rules cũ bị xóa sạch, 3 rules mới thế vào). Các rules tự tay người dùng tạo nếu có flag (Auto=False) phải giữ nguyên. | | |
| **ST_04** | Change State: Kích Hoạt Chiến Lược | Strategy đang có 3 rules trạng thái Nháp. | 1. Bấm nút `Kích hoạt`. | - Strategy chuyển về "Đang Chạy".<br>- TOÀN BỘ 3 Rules bên dưới chuyển `Kích hoạt` (Active=True) hàng loạt. | | |
| **ST_05** | Template 2: Đẩy Hàng Tồn Cao | Chọn Strategy = `Đẩy Tồn Cao`. Ngưỡng Tồn=200, % Budget Tăng=30%. Bấm Sinh Rule. | 1. Xem qua tab Rules. | Sinh ra 2 RUles CHO MỖI SP Map:<br>Rule 1: If Tồn > 200 => Enable Chiến dịch.<br>Rule 2: If Tồn > 200 => Tăng Budget 30%. | | |
| **ST_06** | Template 3: Tối Ưu Lợi Nhuận | Chọn = `Tối ưu lợi nhuận`. Biên LN Min = 15%. Max CPA = 100k. | 1. Sinh Rule. | Sinh ra 2 Rues/SP:<br>1: If CPA > 100k => Pause<br>2: If Margin < 15% => Pause. | | |
| **ST_07** | Template 4: Cân bằng tự động (Auto balance) | Chọn = `Cân Bằng Tự Động`. Khai full thông số (Low=10, High=200, Margin=15%). | 1. Sinh Rule. | Engine gộp toàn bộ rules của 3 kịch bản: Protect_low + Push_stock + Optimize_profit (Tổng 5 rules/SP) để đánh chặn toàn diện rủi ro. | | |
| **ST_08** | Template 5: Custom Custom (Tùy chỉnh cá nhân) | Chọn = `Tùy Chỉnh`. Action: Giảm Budget. Values = Bỏ trống. | 1. Sinh rule. | (1) Ném validation Lỗi nếu user quên điền value/field custom.<br>(2) Nếu điền chuẩn: "If (Field tự chọn) (Toán tử tự chọn) => Giảm budget x%". | | |

## 3. PHÂN HỆ QUY TẮC TỰ ĐỘNG & LỊCH SỬ (RULES & LOGS)

| ID | Tên Kịch Bản | Tiền Điều Kiện | Các Bước Thực Hiện | Kết Quả Mong Đợi | Kết Quả Thực Tế | Ghi Chú / Bug URL |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **RL_01** | Test Toán Tử Kỹ Thuật | Tạo Rule thủ công. Toán tử `=`, Trường `is_new_product`, Value `1`. | 1. Thêm 1 SP mới tạo hôm nay vào Campaign test.<br>2. Bấm `Evaluate (Chạy Thử)`. | Rule quét trúng, ghi log "Đối tượng thoả mãn... Thực tế: 1.0". | | |
| **RL_02** | Dry-run Mode (Tính năng An toàn) | Account / Strategy có `is_live = False` (Tắt Live Mode). Rule đạt điều kiện Pause. | 1. Bấm `Evaluate`.<br>2. Kiểm tra Campaign. | Campaign *KHÔNG BỊ PAUSE* trên Odoo lẫn Google. Log ghi chú an toàn: `[DRY-RUN] Hành động Pause`. | | |
| **RL_03** | Live Mode (Thực thi thật chặn API) | Bật `is_live = True`. Rule đạt điều kiện Pause. | 1. Bấm `Evaluate`. | Campaign lập tức bị chuyển thành `paused` trên hệ thống. Dòng Log lưu Trạng thái `Action_Taken` (Màu xanh). | | |
| **RL_04** | Target Scope: Campaign vs Ad Group | Tạo Rule mục tiêu là "Nhóm Quảng Cáo", set logic Pause nếu COST > 1tr. | 1. Bấm `Evaluate`. | Mutate từ chối (Skip): Log ghi "Mutate chỉ hỗ trợ Campaign, bỏ qua Nhóm QC" do Google API chưa support cấp độ Nhóm trong module này. | | |
| **RL_05** | Fallback Scope (Global Rule) | Tạo Rule KHÔNG điền SP liên kết (Product Feed Line = Empty). | 1. Bấm `Evaluate`. | Rule quét *toàn bộ* các Campaign thuộc Account đó thay vì chỉ 1 Campaign chỉ định. | | |
| **RL_06** | Scheduled Action (Cron Job) | Setup Cron Job On. | 1. Kích hoạt Cron qua Settings. | Cron tự động thực hiện 3 bước: Sync Data -> Refresh Stock -> Run All Rules. Log không phát sinh lỗi traceback. | | |

---

## 4. PHÂN HỆ CHIẾN DỊCH (CAMPAIGNS)

| ID | Tên Kịch Bản | Tiền Điều Kiện | Các Bước Thực Hiện | Kết Quả Mong Đợi | Kết Quả Thực Tế | Ghi Chú / Bug URL |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **CP_01** | Create: Lỗi bắt buộc Validation | Bỏ trống "Ngân sách hàng ngày". | 1. Bấm `Đồng bộ lên Google`. | UI chặn lại báo lỗi bắt buộc điền ngân sách (Odoo default form validation). | | |
| **CP_02** | Create: PMax Validation | Chọn kênh Tối đa Hiệu suất (PMax). Logo để trống. | 1. Bấm `Đồng bộ`. | Hệ thống catch lỗi Google và dịch ra tiếng Việt: "Chiến dịch PMax yêu cầu Tên thương hiệu và Logo. Vui lòng điền đủ...". | | |
| **CP_03** | Create: Shopping / PMax Merchant Center | Chọn kênh Mua Sắm (Shopping). Merchant ID trong Tài khoản bỏ trống. | 1. Bấm `Đồng bộ`. | Odoo quăng UserError: "Vui lòng cấu hình Merchant Center ID trong mục Cài đặt Tài khoản" *TRƯỚC KHI* gọi API. Cứu được 1 API call thừa. | | |
| **CP_04** | Đồng bộ Demo (Demo Account) | Tài khoản bật "Chế độ Demo". | 1. Tạo Campaign. Bấm `Đồng bộ`. | ID Campaign nhảy thành `DEMO_SYNC_[ID]`. Trạng thái chuyển thành "Đã đồng bộ Google". Notification xanh lá. | | |
| **CP_05** | Cơ chế Tìm Thay Vì Lặp (Auto Match Name) | Đổi sang Account LIVE. Campaign tên `TEST_CP_01` đã tồn tại trên GG nhưng ở Odoo chưa có ID. | 1. Tạo campaign mới trên Odoo tên y hệt `TEST_CP_01`. Bấm `Đồng bộ`. | Thay vì tạo mới (ra 2 campaign), Odoo báo Log: "Found existing campaign... Auto-linked". Tự động lấy ID cũ về và chuyển trạng thái Update. | | |
| **CP_06** | Dashboard UX: Xử lý chia 0 (Zero Division) | Campaign mới tạo, Clicks = 0, Cost = 0. | 1. F5 trình duyệt xem thẻ Dashboard HTML. | % Chuyển đổi (CR) = 0%, ROAS = 0x. Không văng lỗi màn hình trắng 500 do chia cho 0. | | |
| **CP_07** | Adsroid AI: Hỏi thủ công | Tính năng AI = Bật. Campaign đã Sync. | 1. Vào form Campaign, ấn `Hỏi Nhận Định Adsroid (AI)`. | Trình duyệt xoay 3-5 giây chờ. Render khối HTML màu xanh chứa Score và lời khuyên Insight. Lưu 1 dòng History vào tab Lịch Sử Adsroid. | | |
| **CP_08** | Adsroid AI: Auto Apply (Cực quan trọng) | Auto-Apply = ON. Đẩy fake data Cost cực cao, tỷ lệ đơn = 0. | 1. Bấm Hỏi AI thủ công (hoặc chờ Cron). | AI khuyên PAUSE. Object chặn được chuỗi "PAUSE" trong suggested_action và lập tức gọi Mutate_Pause. Đẩy Campaign về lại trạng thái Tạm Dừng tự động. | | |

## 5. PHÂN HỆ NHÓM QUẢNG CÁO (AD GROUPS)

| ID | Tên Kịch Bản | Tiền Điều Kiện | Các Bước Thực Hiện | Kết Quả Mong Đợi | Kết Quả Thực Tế | Ghi Chú / Bug URL |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **AG_01** | Tạo Nhóm Search cơ bản | Đã có Chiến dịch Search. | 1. Tạo Nhóm QC Chọn Loại Nhóm = 'Tìm kiếm Chuẩn'. Bấm Đồng bộ. | Trạng thái chuyển thành "Đã đồng bộ". Dashboard vẽ widget thành công. | | |
| **AG_02** | DSA Validation (Tìm kiếm động) | Chọn Chiến dịch Search nhưng *chưa kích hoạt DSA* (Trạng thái tắt DSA ở phía Campaign). | 1. Mục Tùy Chọn Loại Nhóm QC -> Chọn 'SEARCH_DYNAMIC_ADS'. Bấm Đồng Bộ. | Hệ thống quăng lỗi Error (Dịch từ Google): "Nhóm QC Dạng DSA chỉ được tạo khi Chiến dịch chứa cài đặt Search Dynamic Ads". | | |
| **AG_03** | Ràng buộc PMax Ad Group | Đã tạo Campaign loại PMax. | 1. Bấm tạo Nhóm QC. Chọn Campaign PMax đó. | Form UI ngăn chặn thao tác. Hiện Alert "PMax sử dụng Tài sản (Asset Groups) nội bộ, không hỗ trợ tạo Nhóm quảng cáo truyền thống". | | |

---

## 6. PHÂN HỆ MẪU QUẢNG CÁO (ADS)

| ID | Tên Kịch Bản | Tiền Điều Kiện | Các Bước Thực Hiện | Kết Quả Mong Đợi | Kết Quả Thực Tế | Ghi Chú / Bug URL |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **AD_01** | Filter 1: Chọn Group trước -> Lọc ra Ad Type | Form Mẫu QC. | 1. Bấm trường `Nhóm Quảng Cáo` chọn Nhóm thuộc loại Tìm Kiếm.<br>2. Bấm trường `Loại Quảng Cáo`. | Danh sách xổ xuống co lại chỉ hiển thị RSA, Text Ad, Call, Discovery (chứ không hiện Video). | | |
| **AD_02** | Filter 2: Chọn Ad Type trước -> Lọc ra Group | Form Mẫu QC. | 1. Bấm trường `Loại Quảng Cáo` chọn Mua Sắm Sản Phẩm.<br>2. Bấm trường `Nhóm Quảng Cáo`. | Danh sách chỉ hiện những Nhóm thuộc chiến dịch Shopping Product. | | |
| **AD_03** | Tự sửa lỗi Type (Bi-directional filter) | | 1. Chọn Nhóm A (Tìm Kiếm), Chọn Loại B (Image).<br>2. Chọn ngược Nhóm C (Shopping). | Alert màu cam hiện ra: "Lựa chọn không tương thích, tự động đổi về...". Trường Loại tự nhảy về 'Mua Sắm'. | | |
| **AD_04** | Fix URL (HTTPs prefix) | | 1. Gõ `google.com` vào Final URL. 2. Bấm `Lưu` / `Đồng bộ`. | Odoo tự động chèn tiền tố thành `https://google.com`. | | |
| **AD_05** | Validate số Dòng cho RSA (Tiêu đề/Mô tả) | Loại: Tìm kiếm thích ứng (RSA). | 1. Nhập 2 dòng tiêu đề, 1 dòng mô tả. Bấm Đồng Bộ. | Ném rào UserError: "Quảng cáo RSA yếu cầu ít nhất 3 tiêu đề KHÁC NHAU... Bạn gõ trùng". (Kèm logic Deduplication - xóa dòng trùng). | | |
| **AD_06** | Replace Policy (Lách luật Google Immutable) | Mẫu RSA đã có ID, trạng thái Đã Đồng Bộ. Cost/Click = 50. | 1. Đổi nội dung Title. Ấn `Update lên GG`. | - Google xóa QC cũ.<br>- Tạo QC mới có ID mới.<br>- Lịch sử Dashboard Odoo: ID cũ tráo thành MỚI. Số Click = 50 (Vẫn giữ số cũ - Cộng dồn di sản!). | | |

---

## 7. CẤU HÌNH & TÀI KHOẢN (ACCOUNT & GTM)

| ID | Tên Kịch Bản | Tiền Điều Kiện | Các Bước Thực Hiện | Kết Quả Mong Đợi | Kết Quả Thực Tế | Ghi Chú / Bug URL |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **AC_01** | Bật / Tắt Demo Mode | | 1. Tắt cờ Demo chế độ API.<br>2. Bấm `Kiểm tra kết nối`. | Lên báo lỗi nếu nhập bừa Client ID. Đòi điền đúng chuẩn OAuth2 token Google. | | |
| **AC_02** | GTM Readonly UI | Có dữ liệu Tag Manager. | 1. Click Sửa 1 thẻ / Tag ID. | Không sửa được. Nút Lưu vô giá trị vì model cấp `Read-only` để tránh ghi sai data GTM. | | |
| **AC_03** | Render Snippet WooCommerce | Đã cấu hình AW-XXXXXX ở Tag Menu. | 1. Bấm tab `Cài đặt Code Snippet`. | Hiển thị code iframe/html PHP functions đúng chuẩn WordPress, copy là bỏ vào dán dùng được ngay. | | |

---
**Hướng dẫn cho Tester:**
- Cột `Kết Quả Thực Tế` điền: Pass, Fail, Blocked.
- Cột `Ghi Chú` điền URL Ticket Jira nếu có bug hoặc giải thích chi tiết nếu kết quả không như mong đợi.
