# TÀI LIỆU KỸ THUẬT: MISA PURCHASE REQUEST SYNC

## 1. Mục đích Module (Overview)
Module `misa_purchase_request_sync` đảm nhiệm việc đồng bộ một chiều dữ liệu "Yêu cầu mua hàng" (Purchase Request - PR) từ nền tảng **MISA AMIS CRM** sang hệ thống **Odoo**. 
Việc đồng bộ này không thực hiện trực tiếp server-to-server qua API của MISA (do giới hạn API YCMH của MISA), mà thông qua một **Chrome Extension** hoạt động trực tiếp trên trình duyệt của người dùng.

**Luồng hoạt động chính:**
1. Người dùng mở trang chi tiết YCMH trên MISA CRM.
2. Chrome Extension thu thập dữ liệu (Tên YCMH, Người yêu cầu, Đơn hàng bán liên quan, Danh sách hàng hóa, Số lượng...).
3. Extension gửi dữ liệu này tới API Endpoint của Odoo.
4. Odoo nhận dữ liệu, xác thực qua Token tĩnh, sau đó tự động tạo các bản ghi `purchase.request` và `purchase.request.line` tương ứng.
5. Khi YCMH đã tồn tại trên Odoo, Extension hiển thị các nút thao tác (Thu hồi), trạng thái Odoo, và tiến độ nhận hàng (Số lượng đã nhận).

---

## 2. Cấu trúc thư mục (Tree View)
```
misa_purchase_request_sync/
├── controllers/              ← Tầng API giao tiếp với Chrome Extension
│   ├── __init__.py
│   └── extension_api.py      ← Chứa các route: /check, /create, /revoke
├── data/                     ← Dữ liệu khởi tạo (System Parameters)
│   └── ir_config_parameter.xml ← Khởi tạo token xác thực
├── models/                   ← Tầng Model (Kế thừa và mở rộng database)
│   ├── __init__.py
│   ├── purchase_request.py   ← Mở rộng model `purchase.request` của OCA
│   └── purchase_request_line.py ← Mở rộng model `purchase.request.line` của OCA
├── views/                    ← Tầng Giao diện UI Odoo
│   └── purchase_request_view.xml ← Kế thừa form view, thêm field mới
├── __init__.py
├── __manifest__.py           ← Cấu hình module, depends
└── TECHNICAL.md              ← (File này) Tài liệu kỹ thuật chi tiết
```

---

## 3. Data Models & Fields (Kiến trúc Database)

### 3.1. Kế thừa `purchase.request` (OCA)
Module không tự tạo model YCMH mới mà kế thừa trực tiếp từ model `purchase.request` thuộc thư viện của OCA.

**Các trường (Fields) được bổ sung thêm:**
- **`sale_order_id`** (`Many2one` liên kết tới `sale.order`): 
  - **Công dụng:** Lưu vết Đơn bán hàng gốc gây ra nhu cầu mua sắm này. 
  - **Nguồn dữ liệu:** Lấy từ trường "Đơn hàng" trên MISA CRM. Odoo tự động map theo tên đơn hàng (`name`).
- **`delivery_address`** (`Char`): 
  - **Công dụng:** Lưu địa chỉ/kho giao nhận hàng hóa cụ thể.
  - **Lý do dùng Char:** Do dữ liệu MISA trả về dạng text tự do, không map cứng vào ID của model Res Partner.

**Cập nhật trên Form View Odoo (`views/purchase_request_view.xml`):**
- Hiển thị `sale_order_id` và `delivery_address` ngay dưới trường Người yêu cầu (`requested_by`). Cả 2 trường sẽ bị khóa (readonly) nếu YCMH đã ở trạng thái `done` hoặc `rejected`.
- Lôi thêm `create_date` (Ngày tạo) và `write_date` (Ngày sửa) - đây là 2 trường mặc định của Odoo - ra giao diện form để người dùng tiện theo dõi lịch sử.

### 3.2. Kế thừa `purchase.request.line` (OCA)
Kế thừa để hỗ trợ điền tự động và cho phép chọn giá trị tham khảo từ lịch sử mua hàng.

**Các trường (Fields) được bổ sung thêm:**
- **`history_po_line_id`** (`Many2one` liên kết tới `purchase.order.line`):
  - **Công dụng:** Cho phép người dùng chọn một dòng từ lịch sử các đơn mua hàng (PO) đã mua trước đó cho cùng sản phẩm (`product_id`) để lấy giá cũ làm chi phí ước tính.
  - **Logic (`onchange`):**
    - `onchange("product_id")`: Tự động tìm giá mua ưu tiên từ Nhà cung cấp (`product.supplierinfo`), nếu không có thì lấy giá vốn chuẩn (`standard_price`), gán vào `estimated_cost`.
    - `onchange("history_po_line_id")`: Lấy `price_unit` của dòng PO lịch sử đã chọn gán vào `estimated_cost`.
- **Lưu trữ dữ liệu thực mua thực tế (`actual_*`):**
  - Nhóm trường: `actual_qty`, `actual_price_unit`, `actual_tax_id`, `actual_tax_rate`, `actual_discount_rate`, `actual_discount_amount`, `actual_supplier_id`.
  - **Công dụng:** Lưu trữ lại dữ liệu thực tế mà phòng mua hàng đã chỉnh sửa trên Wizard "Tạo RFQ". Khi Wizard chạy (`make_purchase_order`), các giá trị này sẽ được ghi ngược lại `purchase.request.line` tương ứng.
  - **Mục đích:** Khi người dùng mở lại Wizard cho dòng này (ví dụ để tạo lại RFQ bị hủy), Wizard sẽ tự động load lại dữ liệu thực tế đã lưu trước đó thay vì hiển thị dữ liệu sale đề xuất ban đầu.
- **Cột so sánh dữ liệu đề xuất vs thực tế (`display_*_html`):**
  - Nhóm trường HTML: `display_qty_html`, `display_price_unit_html`, `display_tax_rate_html`, `display_discount_rate_html`, `display_supplier_html`.
  - **Công dụng:** Tự động tính toán để hiển thị 2 dòng trong một ô của list view khi PR không còn ở trạng thái `draft`.
    - Dòng trên: Giá trị đề xuất ban đầu (màu đen thường).
    - Dòng dưới: Giá trị thực mua thực tế (màu xanh dương đậm, in nghiêng, bắt đầu bằng chữ `thực: `). Chỉ hiển thị khi có dữ liệu thực tế (sau khi đã chạy wizard Tạo RFQ và lưu lại), nếu chưa tạo RFQ thì không hiển thị dòng `thực:` này.
  - **Giao diện XML:**
    - Ở list view của Form Yêu cầu mua hàng (`view_purchase_request_form_inherit_misa_sync`), các trường nhập liệu gốc chỉ hiển thị ở trạng thái `draft` (`column_invisible="parent.state != 'draft'"`).
    - Khi ở các trạng thái khác, các trường HTML so sánh được hiển thị thay thế (`column_invisible="parent.state == 'draft'"`), giúp quản lý và đối chiếu dễ dàng mà không làm hỏng tính năng edit của Odoo.

**Cập nhật trên Form View Odoo:**
- Hiển thị `history_po_line_id` trong danh sách (tree view) của `line_ids` (nằm cạnh `estimated_cost`).
- Hiển thị trong form chi tiết của `purchase.request.line`.

### 3.3. Computed Fields: Tiến độ mua hàng (v1.1.0+)

Module bổ sung các computed fields trên `purchase.request` để hiển thị tiến độ mua hàng trong list view:

- **`progress_total`** (`Integer`, `store=True`): Tổng số dòng yêu cầu (không tính dòng đã hủy).
- **`progress_purchased`** (`Integer`, `store=True`): Số dòng đã có Đơn mua hàng (PO/RFQ).
- **`progress_received`** (`Integer`, `store=True`): Số dòng đã nhận đủ hàng.
- **`progress_badge`** (`Char`, `store=True`): Hiển thị gọn dạng `ĐH 4/5 • NK 3/5` = đã tạo ĐH 4/5, đã nhận 3/5.
- **`progress_status`** (`Selection`, `store=True`): Trạng thái tiến độ, dùng cho `decoration-*` trong list view:
  - `not_started`: Chưa có PO nào (muted/xám)
  - `in_progress`: Đang mua (info/xanh dương)
  - `partial`: Nhận một phần (warning/vàng)
  - `done`: Hoàn thành (success/xanh lá)

**Logic computed (`_compute_purchase_progress`):**
- Lọc `active_lines = line_ids.filtered(lambda l: not l.cancelled)`
- `purchased`: Đếm dòng có `purchase_lines` với `state != 'cancel'`
- `received`: Đếm dòng có `qty_done >= product_qty` (hoặc `purchase_state == 'done'` và `qty_done > 0`)

**View XML:**
- Kế thừa `view_purchase_request_tree` thêm cột `progress_badge` với `widget="badge"` và `decoration-*` dựa trên `progress_status`.

### 3.4. Thông số hệ thống (`ir.config_parameter`)
- **Key:** `misa_extension_token`
- **Công dụng:** Chứa mã token dùng để xác thực các request đẩy từ Chrome Extension sang. 
- **Đặc điểm:** 
  - Được khai báo trong XML với `noupdate="1"` và `eval="''"`. 
  - Nghĩa là khi cài module, nó sẽ tạo ra record trống. Quản trị viên phải vào *Settings > Technical > System Parameters* để nhập token thật. Khi upgrade module, giá trị này **không bị ghi đè**.

### 3.5. Hàng chờ đồng bộ (`misa.sync.queue`)
Để tránh tắc nghẽn và xung đột khi đồng bộ dữ liệu real-time từ Extension, hệ thống sử dụng một queue trung gian.

- **Cơ chế chống Race Condition (Tranh chấp ghi dữ liệu)**:
  - Khi Cron Job quét các bản ghi `draft`, hệ thống sử dụng câu lệnh SQL atomic `SELECT ... FOR UPDATE SKIP LOCKED` thay vì ORM `search()`.
  - Giúp nhiều worker (Cron hoặc bấm nút tay thủ công) xử lý song song các bản ghi khác nhau mà không bao giờ bị trùng lặp hoặc khóa lẫn nhau (Deadlock).
- **Cơ chế phục hồi bản ghi bị kẹt (Zombie Recovery)**:
  - Trường hợp Worker/Odoo crash hoặc restart đột ngột khi đang xử lý bản ghi (`state='processing'`).
  - Trường `processing_started_at` lưu thời điểm bắt đầu xử lý.
  - Khi Cron chạy, nó tự động tìm các bản ghi kẹt ở trạng thái `processing` quá 10 phút, cộng `retry_count`.
  - Nếu `retry_count < 3`, đưa về `draft` và đẩy xuống cuối hàng (`sequence += 10`) để xử lý lại. Nếu `>= 3` lần bị timeout/lỗi liên tiếp, đánh dấu là `failed` và ghi nhận nhật ký lỗi.
