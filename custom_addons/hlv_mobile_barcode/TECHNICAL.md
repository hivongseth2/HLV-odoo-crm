# Tài liệu kỹ thuật: HLV Mobile Barcode

> **Phiên bản**: 18.0.1.0.0 · **Nền tảng**: Odoo 18 · **Công nghệ giao diện**: OWL 2.0

---

# PHẦN 1 – TỔNG QUAN

## 1.1. Mục đích module

HLV Mobile Barcode là ứng dụng quét mã vạch tối ưu cho điện thoại di động (Mobile Web), hoạt động trực tiếp trên trình duyệt web mà không cần cài đặt ứng dụng riêng. Module thay thế hoàn toàn giao diện Barcode gốc của Odoo, cung cấp trải nghiệm nhanh hơn, trực quan hơn và phù hợp hơn cho thao tác một tay trong kho hàng thực tế.

## 1.2. Các chức năng chính

| STT | Chức năng | Mô tả ngắn |
|-----|-----------|-------------|
| 1 | **Quét thông minh (Smart Routing)** | Chỉ cần quét 1 mã bất kỳ (sản phẩm, vị trí, phiếu kho, kiện hàng), hệ thống tự nhận diện loại mã và chuyển đến màn hình tương ứng. Không cần chọn trước thao tác. |
| 2 | **Xử lý phiếu kho (Picking Scanner)** | Quét sản phẩm để tăng số lượng hoàn thành trên phiếu kho. Hỗ trợ đầy đủ các loại phiếu: Nhập (IN), Xuất (OUT), Chuyển nội bộ (INT), Lấy hàng (PICK), Đóng gói (PACK), Lưu kho (STO). |
| 3 | **Quét camera tích hợp** | Camera điện thoại nhúng trực tiếp trên giao diện, quét liên tục không cần bấm nút. Hỗ trợ quét bằng súng USB, dán mã (Ctrl+V), hoặc gõ tay. |
| 4 | **Tra cứu tồn kho** | Quét mã sản phẩm / vị trí / kiện hàng để xem tồn kho theo cây vị trí phân cấp, bao gồm cả vị trí con. |
| 5 | **Chuyển vị trí hàng hóa** | Tạo phiếu chuyển kho nội bộ (Internal Transfer) để di chuyển sản phẩm từ vị trí này sang vị trí khác, tự động xác nhận phiếu. Hỗ trợ cấu hình cùng kho khác vị trí đi 1 bước hoặc 2 bước qua Transit. |
| 6 | **Chuyển kho đa vị trí** | Gom hàng từ nhiều kệ (vị trí con) khác nhau vào một phiếu chuyển kho chung. Phù hợp cho nghiệp vụ dọn kho, gom hàng. |
| 7 | **Quản lý kiện hàng (Đóng gói)** | Đóng gói sản phẩm đã quét thành kiện (Package), gỡ kiện, chỉnh sửa số lượng trong kiện, chuyển sản phẩm giữa các kiện. Hỗ trợ in nhãn kiện tự động. |
| 8 | **Liên kết quy trình 2 bước** | Khi hoàn thành phiếu Bước 1 (ví dụ INT), hệ thống tự tìm và hiển thị nút chuyển nhanh sang phiếu Bước 2 (IN / STO). |
| 9 | **Phân quyền quét kho** | Hệ thống phân quyền linh hoạt theo Người dùng × Kho × Loại phiếu, với 4 cấp quyền: Xem, Sửa, Xóa, Xác nhận. |
| 10 | **Chống gian lận** | Chặn sao chép mã vạch từ giao diện (chống bôi đen, chặn chuột phải, chặn Ctrl+C). Giới hạn quét theo tồn kho thực tế. |

## 1.3. Cấu trúc thư mục

```
hlv_mobile_barcode/
├── controllers/
│   ├── __init__.py
│   └── main.py                  ← Toàn bộ API JSON-RPC (Smart Routing, xử lý quét, đóng gói…)
├── models/
│   ├── __init__.py
│   ├── barcode_permission.py    ← Model phân quyền quét kho (2 model mới)
│   ├── res_config_settings.py   ← Cấu hình ứng dụng (kế thừa res.company & res.config.settings)
│   ├── stock_move_line.py       ← Mở rộng stock.move.line: thêm field qty_scanned cho PICK
│   └── stock_picking.py         ← Mở rộng stock.picking (thêm field cờ đánh dấu)
├── security/
│   ├── security.xml             ← Nhóm quyền: Quản lý phân quyền Barcode
│   └── ir.model.access.csv      ← Quyền truy cập cho 2 model mới
├── static/src/
│   ├── components/              ← Các component OWL 2.0
│   │   ├── barcode_app/         ← Component cha: quản lý state, camera, điều hướng
│   │   ├── picking_scanner/     ← Xử lý phiếu kho: quét, đóng gói, xác nhận
│   │   ├── inventory_lookup/    ← Tra cứu tồn kho theo sản phẩm/vị trí/kiện
│   │   ├── location_move/       ← Chuyển vị trí đơn lẻ
│   │   └── batch_location_move/ ← Chuyển kho đa vị trí (gom từ nhiều kệ)
│   └── css/
│       └── barcode_mobile.css   ← Hệ thống thiết kế giao diện (design tokens, responsive)
├── views/
│   ├── barcode_menu.xml         ← Client Action mở ứng dụng OWL
│   ├── barcode_permission_views.xml ← Giao diện quản lý phân quyền quét
│   └── res_config_settings_views.xml ← Trang Cài đặt ứng dụng
├── __init__.py
└── __manifest__.py
```

---

# PHẦN 2 – CHI TIẾT KỸ THUẬT

## 2.1. Kiến trúc tổng thể

Ứng dụng hoạt động theo mô hình **Client Action OWL + JSON-RPC Backend**:

```
┌─────────────────────────────────────────────────┐
│                 TRÌNH DUYỆT (OWL 2.0)           │
│                                                 │
│  barcode_app (Component cha)                    │
│   ├── Camera nhúng (BarcodeDetector API)        │
│   ├── Ô nhập mã ẩn / hiển thị                  │
│   ├── picking_scanner (Xử lý phiếu kho)        │
│   ├── inventory_lookup (Tra cứu tồn kho)       │
│   ├── location_move (Chuyển vị trí)             │
│   └── batch_location_move (Chuyển đa vị trí)   │
│                     │                           │
│              JSON-RPC calls                     │
└─────────────────┬───────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────┐
│              MÁY CHỦ ODOO 18                    │
│                                                 │
│  controllers/main.py                            │
│   ├── /smart_scan         (nhận diện mã)        │
│   ├── /get_picking_data   (tải dữ liệu phiếu)  │
│   ├── /process_barcode    (xử lý quét)          │
│   ├── /put_in_pack        (đóng gói)            │
│   ├── /validate_picking   (xác nhận phiếu)      │
│   ├── /get_inventory_lookup (tra cứu tồn)       │
│   ├── /move_location      (chuyển vị trí)       │
│   └── ... (các endpoint quản lý kiện hàng)      │
│                                                 │
│  models/                                        │
│   ├── barcode_permission.py (phân quyền)        │
│   ├── res_config_settings.py (cấu hình)         │
│   └── stock_picking.py (mở rộng phiếu kho)      │
└─────────────────────────────────────────────────┘
```

## 2.2. Model dữ liệu

### 2.2.1. Model mới: `hlv.barcode.user.permission`

Quản lý phân quyền quét kho theo cặp **Người dùng × Kho**.

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `user_id` | Many2one → `res.users` | Người dùng (chỉ user nội bộ, `share=False`) |
| `warehouse_id` | Many2one → `stock.warehouse` | Kho được cấp quyền |
| `picking_permission_ids` | One2many → `hlv.barcode.picking.permission` | Danh sách quyền theo loại phiếu |

- **Ràng buộc SQL**: Mỗi user chỉ có 1 bản ghi phân quyền cho mỗi kho (`unique(user_id, warehouse_id)`).
- **Phương thức `check_picking_operation()`**: Kiểm tra quyền thực thi. Nếu user chưa có bản ghi phân quyền nào → cho phép mặc định (tương thích ngược). Nếu có bản ghi cho kho khác nhưng không có cho kho hiện tại → từ chối.
- **Phương thức `action_generate_all()`**: Tạo hàng loạt phân quyền cho tất cả user nội bộ × tất cả kho với quyền mặc định bật hết.

### 2.2.2. Model mới: `hlv.barcode.picking.permission`

Quyền chi tiết cho từng loại phiếu, liên kết con của `hlv.barcode.user.permission`.

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `permission_id` | Many2one → `hlv.barcode.user.permission` | Bản ghi phân quyền cha |
| `picking_type_code` | Selection | Loại phiếu: `IN`, `OUT`, `INT`, `PICK`, `PACK`, `STO` |
| `can_view` | Boolean | Quyền xem / quét phiếu |
| `can_edit` | Boolean | Quyền sửa / quét hàng vào phiếu |
| `can_delete` | Boolean | Quyền xóa dòng sản phẩm |
| `can_confirm` | Boolean | Quyền xác nhận (validate) phiếu |

- **Ràng buộc SQL**: Mỗi loại phiếu chỉ xuất hiện 1 lần trong mỗi bản ghi phân quyền cha (`unique(permission_id, picking_type_code)`).

### 2.2.3. Model kế thừa: `res.company` & `res.config.settings`

Mở rộng cấu hình hệ thống với các tham số:

| Tham số | Kiểu | Mô tả |
|---------|------|-------|
| `hlv_barcode_picking_type_ids` | Many2many → `stock.picking.type` | Danh sách loại phiếu hiển thị trên ứng dụng quét |
| `hlv_barcode_print_after_pack` | Boolean | In nhãn tự động sau khi đóng gói |
| `hlv_barcode_use_independent_permissions` | Boolean (config_parameter) | Nút gạt chọn nguồn phân quyền: riêng module hoặc dùng chung `hlv_warehouse_permission` |
| `hlv_barcode_allow_package_scan` | Boolean (config_parameter) | Cho phép quét mã kiện hàng để hoàn thành hàng loạt |
| `hlv_barcode_show_qty_buttons` | Boolean (config_parameter) | Hiển thị nút +1/-1/+10/-10 trên giao diện quét |
| `hlv_barcode_camera_default_on` | Boolean (config_parameter) | Camera tự động bật khi vào phiếu |
| `hlv_barcode_same_warehouse_one_step` | Boolean (config_parameter, mặc định `True`) | Bật: chuyển giữa các vị trí trong cùng kho đi thẳng 1 bước. Tắt: cùng kho khác vị trí cũng đi qua Transit và tạo quy trình 2 bước |

### 2.2.4. Model kế thừa: `stock.picking`

Thêm 1 trường cờ đánh dấu:

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `hlv_barcode_auto_cleared` | Boolean | Đánh dấu phiếu đã được tự động làm mới số lượng khi mở lần đầu từ ứng dụng quét |

## 2.3. Nhóm quyền bảo mật

- **Nhóm `group_barcode_permission_manager`**: Quyền quản lý bảng phân quyền quét. Tự động gán cho `stock.group_stock_manager` (Quản lý kho) thông qua `implied_ids`.
- **Quyền truy cập model**:
  - Manager: Đọc / Ghi / Tạo / Xóa trên cả 2 model phân quyền.
  - User kho (`stock.group_stock_user`): Chỉ được Đọc (để hệ thống kiểm tra quyền qua RPC).

## 2.4. Luồng xử lý chính (Workflow)

### 2.4.1. Luồng quét thông minh (Smart Routing)

```
Người dùng quét/nhập mã
        │
        ▼
  barcode_app.processBarcode()
        │
        ▼
  RPC → /smart_scan (gửi mã vạch)
        │
        ▼
  Backend tìm kiếm theo thứ tự ưu tiên:
  1. stock.picking  (khớp name)
  2. product.product (khớp barcode hoặc default_code)
  3. stock.location  (khớp barcode hoặc name)
  4. stock.quant.package (khớp name)
        │
        ▼
  Trả về {type, id, name, warehouse_code}
        │
        ▼
  Frontend chuyển đổi currentView:
  - type='picking'  → mở picking_scanner
  - type='product'  → mở inventory_lookup
  - type='location' → mở inventory_lookup
  - type='package'  → mở inventory_lookup
```

**Lưu ý kỹ thuật**:
- Toàn bộ truy vấn `search()` sử dụng `.sudo()` để bỏ qua rào cản phân quyền multi-company.
- Hỗ trợ khớp song song: mã vạch (`barcode`) và mã nội bộ/SKU (`default_code`) cho sản phẩm; mã vạch (`barcode`) và tên (`name`) cho vị trí.
- Chuỗi quét được tự động `.strip()` để loại bỏ khoảng trắng thừa từ máy quét.

### 2.4.2. Luồng xử lý phiếu kho (Picking Scanner)

```
Mở phiếu → RPC /get_picking_data
        │
        ▼
  Hiển thị danh sách sản phẩm cần xử lý
  (phân tách: hàng lẻ + kiện hàng đã đóng gói)
        │
        ▼
  Quét sản phẩm → RPC /process_barcode
        │
        ├─ Nếu là mã sản phẩm: +1 số lượng hoàn thành
        ├─ Nếu là mã vị trí: gán vị trí nguồn cho các lần quét tiếp theo
        └─ Nếu là mã kiện hàng: hoàn thành hàng loạt tất cả sản phẩm trong kiện
        │
        ▼
  Khi đủ số lượng → Xác nhận phiếu (RPC /validate_picking)
```

**Chi tiết kỹ thuật xử lý quét sản phẩm (`/process_barcode`)**:
- **Phân giải vị trí con**: Khi quét vị trí cha (ví dụ `A1-T1`) nhưng tồn kho thực tế nằm ở vị trí con (`A1-T1/THUNG-1`), hệ thống dùng toán tử `child_of` để tìm và gán đúng vị trí con vào `location_id` của `stock.move.line`.
- **Giới hạn theo tồn kho thực tế**: Tính tổng số lượng đã quét cho cùng sản phẩm trên toàn bộ phiếu (tất cả move, tất cả vị trí con) rồi so sánh với `stock.quant`. Nếu vượt quá → chặn quét, trả lỗi.
- **Quét kiện hàng**: Kiểm tra xem phiếu có dòng `move.line` khớp `package_id` không. Nếu có → hoàn thành các dòng đó. Nếu không → tra cứu `stock.quant` trong kiện, tự động khớp và cập nhật số lượng hàng loạt.
- **Bỏ qua sản phẩm đã đóng gói**: Khi quét sản phẩm đã có trong kiện, hệ thống tạo dòng `move.line` mới thay vì ghi đè số lượng kiện.

**Lọc đặc biệt cho phiếu PICK**:
- Backend chỉ trả về các dòng dịch chuyển đã có vị trí nguồn được phân bổ (`move_line_ids` tồn tại).
- Nếu chưa có dòng nào hợp lệ → trả lỗi yêu cầu chờ hệ thống phân bổ, chặn từ trang chủ không cho vào phiếu.
- Phiếu PICK dùng field riêng `stock.move.line.qty_scanned` để lưu tiến độ quét. Frontend hiển thị `qty_done = qty_scanned`, không ghi trực tiếp vào `quantity` trong lúc quét để tránh bị Odoo assign/unreserve hoặc background job ghi đè.
- Khi hiển thị từng dòng PICK, `product_uom_qty` trên UI được lấy theo `ml.quantity` của chính move line đó. Ví dụ sản phẩm A cần 10 nhưng được phân bổ 4 ở kệ A và 6 ở kệ B thì UI hiển thị hai dòng `/4` và `/6`, không lặp tổng `/10` cho cả hai dòng.
- Giới hạn quét PICK:
  - Tổng số quét của sản phẩm không vượt quá `min(move.product_uom_qty, tổng quantity đã assign)`.
  - Từng move line không vượt quá `ml.quantity` tại vị trí đó.
  - Kiểm tra tồn vật lý dùng `qty_scanned` cho PICK và `quantity` cho các loại phiếu khác.
- Khi vào lại phiếu PICK đã có `qty_scanned`, API `/check_pick_scanned_availability` kiểm tra lại mức khả dụng theo từng move line. Nếu có xung đột, popup chỉ cho chọn:
  - Đặt về 0, quét lại từ đầu.
  - Lấy số tối đa khả dụng (`/cap_pick_scanned_to_available`), trong đó mức tối đa cũng bị chặn bởi `ml.quantity` của từng dòng.
- Khi validate PICK, backend mới ghi `quantity = qty_scanned` ngay trước khi gọi xử lý hoàn tất của Odoo.

**Phiếu trả hàng (`stock.picking.return_id`)**:
- Bất kỳ phiếu nào có `return_id` đều được nhận diện là phiếu trả hàng, không phụ thuộc operation type là `INT`, `IN`, `OUT`, `PICK` hay `PACK`.
- Phiếu trả hàng được miễn chốt chặn OUT/PACK của mobile scanner. OUT/PACK không có `return_id` vẫn bị chặn như cũ.
- Phiếu trả hàng không dùng logic PICK độc lập, kể cả khi operation type chứa PICK:
  - `is_pick` trong response bị ép về `False`.
  - Không dùng `qty_scanned`.
  - Không gọi popup conflict `/check_pick_scanned_availability`.
  - Không copy `qty_scanned -> quantity` lúc validate.
- Trong lúc quét và sửa số lượng, phiếu trả hàng luôn dùng field Odoo chuẩn `stock.move.line.quantity`.
- Vị trí nguồn/đích của phiếu trả hàng không đảo thủ công trong module mobile. Odoo tạo phiếu return từ wizard với source/destination đã đảo theo phiếu gốc.
- Khi phiếu đã hoàn tất (`state = done`), footer `PickingScanner` hiển thị nút **Trả hàng**. Nút này mở popup mobile custom dựa trên wizard `stock.return.picking`, cho phép sửa số lượng hoặc xóa dòng trước khi tạo phiếu return.
- Hai thao tác trong popup:
  - **Trả hàng**: gọi `stock.return.picking.action_create_returns()`.
  - **Trả tất cả**: gọi `stock.return.picking.action_create_returns_all()`. Nếu môi trường Odoo không có method này, backend trả lỗi rõ ràng.
- Sau khi tạo thành công, frontend đóng popup và mở ngay phiếu return mới bằng `onSelectPicking(return_picking_id, return_picking_name)`.

### 2.4.3. Luồng đóng gói kiện hàng

```
Quét xong sản phẩm (có qty_done > 0, chưa thuộc kiện nào)
        │
        ▼
  Bấm "Đóng gói" → RPC /put_in_pack
        │
        ▼
  Backend gọi picking._put_in_pack() của Odoo
  Trả về: package_name, print_after_pack
        │
        ▼
  Nếu print_after_pack = true → Mở tab in nhãn kiện

Quản lý kiện hàng (Modal chỉnh sửa):
  - RPC /get_package_details      → Lấy chi tiết kiện
  - RPC /update_package_item_qty  → Chỉnh số lượng trong kiện
  - RPC /remove_package_item      → Gỡ sản phẩm khỏi kiện
  - RPC /add_item_to_package      → Thêm hàng lẻ vào kiện
  - RPC /transfer_item_between_packages → Chuyển giữa các kiện
  - RPC /unpack_move_line         → Gỡ toàn bộ kiện về hàng lẻ
```

### 2.4.4. Luồng liên kết quy trình 2 bước

Quy tắc tạo 1 bước/2 bước khi chuyển vị trí:
- Khác kho: luôn đi qua Transit và tạo quy trình 2 bước.
- Cùng kho khác vị trí:
  - `hlv_barcode_same_warehouse_one_step = True` (mặc định): chuyển thẳng từ vị trí nguồn sang vị trí đích trong 1 bước.
  - `hlv_barcode_same_warehouse_one_step = False`: cũng đi qua Transit và tạo bước 2 như chuyển khác kho.
- Khi cần ép bước 2 về một vị trí đích cụ thể, phiếu bước 1 lưu marker `DEST_LOC_OVERRIDE:<location_id>` trong `note`; sau khi Odoo sinh bước 2, backend cập nhật `location_dest_id` của `stock.picking`, `stock.move`, `stock.move.line` bước 2 về vị trí đích này.

```
Phiếu Bước 1 (INT) hoàn thành (state = 'done')
        │
        ▼
  Backend tìm phiếu Bước 2 qua 4 phương pháp:
  1. Tin nhắn Chatter: tìm mail.message có body chứa tên phiếu Bước 1
  2. Chuỗi dịch chuyển: move_dest_ids.picking_id
  3. Nhóm cung ứng: cùng group_id, mã chứa 'IN'/'STOR'
  4. Nguồn gốc: trường origin khớp tên phiếu Bước 1
        │
        ▼
  Trả về linked_picking_id, linked_picking_name
        │
        ▼
  Frontend hiển thị nút "Chuyển sang Bước 2"
  → Bấm: giải phóng camera, pushHistory(), mở phiếu mới
```

### 2.4.5. Luồng chuyển kho đa vị trí

```
Chọn "Chuyển kho đa vị trí" từ trang tra cứu vị trí
        │
        ▼
  Popup chọn vị trí đích (quét hoặc chọn kho)
        │
        ▼
  RPC /create_empty_int → Tạo phiếu INT trống
  (location_id = lot_stock_id của kho nguồn)
  - Nếu đích cùng kho và setting 1 bước bật: location_dest_id = vị trí đích
  - Nếu đích khác kho hoặc setting 1 bước tắt: location_dest_id = Transit,
    note có DEST_LOC_OVERRIDE để bước 2 đi về đúng vị trí đích
        │
        ▼
  Yêu cầu quét vị trí nguồn (kệ cụ thể) TRƯỚC
        │
        ▼
  Quét sản phẩm → Backend tạo stock.move.line
  với ml_src_id trỏ thẳng vào vị trí con đã quét
        │
        ▼
  Quét vị trí mới → Đổi kệ nguồn cho các lần quét tiếp theo
```

### 2.4.6. Luồng phân quyền quét kho

```
Mỗi RPC endpoint kiểm tra quyền:
        │
        ▼
  Đọc config_parameter: hlv_barcode_use_independent_permissions
        │
        ├─ True  → Truy vấn hlv.barcode.user.permission
        └─ False → Truy vấn warehouse.user.permission (module hlv_warehouse_permission)
        │
        ▼
  request.env.get(model_name)
  (nếu module chưa cài → trả None → cho phép mặc định, không crash)
        │
        ▼
  Gọi check_picking_operation(user, warehouse, type_code, 'can_edit')
        │
        ▼
  Nếu không có quyền → trả lỗi 403 qua JSON response
```

## 2.5. Danh sách API (JSON-RPC Controllers)

| Endpoint | Phương thức | Mô tả |
|----------|-------------|-------|
| `/hlv_mobile_barcode/smart_scan` | POST | Nhận diện mã vạch, trả về loại đối tượng và thông tin |
| `/hlv_mobile_barcode/get_picking_data` | POST | Tải chi tiết phiếu kho (dòng sản phẩm, kiện hàng, liên kết 2 bước) |
| `/hlv_mobile_barcode/process_barcode` | POST | Xử lý quét sản phẩm/vị trí/kiện trong phiếu kho |
| `/hlv_mobile_barcode/update_move_line_qty` | POST | Cập nhật số lượng thủ công trên dòng sản phẩm |
| `/hlv_mobile_barcode/delete_move` | POST | Xóa dòng sản phẩm khỏi phiếu |
| `/hlv_mobile_barcode/validate_picking` | POST | Xác nhận phiếu kho |
| `/hlv_mobile_barcode/clear_quantities` | POST | Xóa sạch số lượng đã quét (reset phiếu) |
| `/hlv_mobile_barcode/get_return_wizard_data` | POST | Tạo và đọc dữ liệu wizard trả hàng `stock.return.picking` cho phiếu đã hoàn tất |
| `/hlv_mobile_barcode/create_return` | POST | Cập nhật dòng wizard, gọi tạo phiếu trả hàng và trả về phiếu return mới |
| `/hlv_mobile_barcode/check_pick_scanned_availability` | POST | Kiểm tra `qty_scanned` đã lưu của phiếu PICK khi vào lại phiếu, phát hiện dòng vượt mức khả dụng hiện tại |
| `/hlv_mobile_barcode/cap_pick_scanned_to_available` | POST | Tự động giảm `qty_scanned` của từng move line PICK xuống mức khả dụng và không vượt `ml.quantity` |
| `/hlv_mobile_barcode/put_in_pack` | POST | Đóng gói các sản phẩm lẻ đã quét thành kiện |
| `/hlv_mobile_barcode/unpack_move_line` | POST | Gỡ sản phẩm khỏi kiện về hàng lẻ |
| `/hlv_mobile_barcode/get_package_details` | POST | Lấy chi tiết kiện hàng để chỉnh sửa |
| `/hlv_mobile_barcode/update_package_item_qty` | POST | Chỉnh số lượng sản phẩm trong kiện |
| `/hlv_mobile_barcode/remove_package_item` | POST | Gỡ sản phẩm khỏi kiện |
| `/hlv_mobile_barcode/add_item_to_package` | POST | Thêm hàng lẻ vào kiện |
| `/hlv_mobile_barcode/transfer_item_between_packages` | POST | Chuyển sản phẩm giữa các kiện |
| `/hlv_mobile_barcode/get_inventory_lookup` | POST | Tra cứu tồn kho (sản phẩm/vị trí/kiện) |
| `/hlv_mobile_barcode/move_location` | POST | Tạo phiếu chuyển vị trí và tự động xác nhận |
| `/hlv_mobile_barcode/create_empty_int` | POST | Tạo phiếu INT trống cho chế độ chuyển đa vị trí |
| `/hlv_mobile_barcode/get_settings` | POST | Lấy cấu hình ứng dụng (camera mặc định, nút số lượng…) |
| `/hlv_mobile_barcode/get_warehouses` | POST | Lấy danh sách kho để chọn đích chuyển |

## 2.6. Kiến trúc giao diện (OWL 2.0)

### 2.6.1. Cây component

| Component | File | Vai trò |
|-----------|------|---------|
| `BarcodeApp` | `barcode_app/` | Component cha: quản lý state toàn cục, camera, điều hướng, lịch sử duyệt, xử lý mã quét |
| `PickingScanner` | `picking_scanner/` | Hiển thị và xử lý phiếu kho: danh sách sản phẩm, kiện hàng, modal chỉnh sửa kiện, footer xác nhận |
| `InventoryLookup` | `inventory_lookup/` | Tra cứu tồn kho: hiển thị quant theo vị trí, sản phẩm đang giữ hàng (reserved) |
| `LocationMove` | `location_move/` | Giao diện chuyển vị trí đơn lẻ |
| `BatchLocationMove` | `batch_location_move/` | Giao diện chuyển kho đa vị trí |

### 2.6.2. Quản lý trạng thái (State Management)

- Sử dụng `useState` của OWL 2.0 để quản lý reactive state trong `BarcodeApp`.
- Trạng thái chính `currentView` quyết định component con nào được hiển thị: `'main'`, `'picking'`, `'lookup'`, `'move'`, `'batch_move'`.
- Lịch sử duyệt (`history[]`) được quản lý thủ công qua `pushHistory()` / `goBack()` để cho phép quay lại nhiều cấp.
- Trạng thái được lưu vào `sessionStorage` để giữ nguyên khi F5/reload, và xóa khi quay lại trang chủ.

### 2.6.3. Camera nhúng liên tục

- Sử dụng **BarcodeDetector API** (native trên trình duyệt hiện đại hoặc polyfill từ jsdelivr).
- Quét qua vòng lặp `requestAnimationFrame` nhẹ nhàng, tạm dừng 2 giây khi quét trùng mã.
- Trạng thái camera mặc định (`camera_default_on`) được tải từ backend qua `/get_settings` và chờ đợi (`await`) trước khi mở camera để tránh Race Condition.
- **Xử lý quyền camera di động**:
  - Kiểm tra `window.isSecureContext` → yêu cầu HTTPS.
  - iOS/Safari: hiển thị lớp phủ yêu cầu user gesture trước khi gọi `getUserMedia()`.
  - Giải phóng camera triệt để khi chuyển view: `stream.getTracks().forEach(t => t.stop())`.

### 2.6.4. Ô nhập mã thông minh

- **Trong các view chi tiết**: Ô input ẩn (`hiddenInputRef`) tự động nhận focus qua cơ chế kiểm tra định kỳ 2 giây. Cho phép quét bằng súng USB hoặc dán mã (Ctrl+V) rồi nhấn Enter.
- **Tại trang chủ**: Focus tự động chuyển sang ô nhập mã hiển thị (`manualInputRef`). Thuộc tính `inputmode="none"` được gán mặc định để ngăn bàn phím ảo mở tự động trên điện thoại. Khi người dùng nhấn vào ô nhập → chuyển `inputmode` sang `"text"`, thực hiện `blur()` rồi `focus()` để kích hoạt bàn phím ảo. Khi mất focus → đưa `inputmode` về `"none"`.

### 2.6.5. Phản hồi cảm giác (Feedback)

- **Âm thanh**: Phát `success.mp3` hoặc `error.mp3` qua Web Audio API.
- **Rung**: `navigator.vibrate(150)` khi thành công, `navigator.vibrate([100, 50, 100])` khi lỗi.
- **Nháy sáng**: Dòng sản phẩm vừa quét được highlight với hiệu ứng CSS animation.

## 2.7. Cơ chế bảo mật

### 2.7.1. Chống gian lận quét

- **Chặn sao chép**: CSS `user-select: none`, chặn sự kiện `copy` và `contextmenu` trên toàn ứng dụng.
- **Giới hạn tồn kho**: Số lượng quét bị chặn khi vượt tồn kho thực tế tại cây vị trí nguồn.
- **Khóa xử lý đơn (isProcessing)**: Ngăn Race Condition khi quét nhanh hoặc mạng chập chờn. Chỉ cho phép 1 RPC chạy tại 1 thời điểm.
- **Khóa số lượng (isProcessingQty)**: Ngăn xung đột khi bấm nút +/- hoặc nhập số lượng thủ công song song.

### 2.7.2. Đồng bộ dữ liệu khi mất kết nối

- **F5/Reload**: `sessionStorage` lưu trạng thái hiện tại, `localStorage` lưu `hlv_opened_pickings` → tải lại an toàn từ backend.
- **Thoát phiếu PICK**: Không tự động xóa `qty_scanned`; thủ kho có thể thoát ra và vào lại để tiếp tục tiến độ đã quét.
- **Vào lại phiếu PICK có dữ liệu đã quét**: Frontend gọi `/check_pick_scanned_availability`. Nếu tồn/phân bổ đã thay đổi, popup bắt buộc người dùng chọn reset về 0 hoặc cap về mức tối đa khả dụng; không còn lựa chọn bỏ qua giữ nguyên.
- **Reset thủ công**: Gọi RPC `/clear_quantities`. Với PICK, chỉ reset `qty_scanned` về 0 và không đụng vào `quantity` do Odoo quản lý; với phiếu khác, reset `quantity`/dòng tạo động theo logic cũ.

### 2.7.3. Bỏ qua phân quyền Odoo (Sudo Bypass)

- Toàn bộ truy vấn `search()` và `browse()` liên quan đến sản phẩm, vị trí, phiếu kho, kiện hàng đều sử dụng `.sudo()` để bỏ qua record rules multi-company.
- Lý do: Nhân viên kho cần thấy 100% dữ liệu thực tế mà không bị chặn bởi các quy tắc phân quyền ngầm định của Odoo ORM.

## 2.8. Thiết kế giao diện (CSS)

- **Hệ thống biến thiết kế (Design Tokens)**: Sử dụng CSS variables trong `:root` với tông màu slate-navy (`--primary-color: #1e293b`), các biến màu nền pastel cho trạng thái (`--success-bg`, `--danger-bg`, `--warning-bg`).
- **Bố cục 1 cột**: Giao diện đồng nhất cho mobile và desktop, tránh lỗi hiển thị chéo nền tảng.
- **Xử lý viewport Odoo**: Dùng `position: absolute !important` trên `.hlv-barcode-app` bám khít `.o_content` để tránh tràn footer do thanh navbar Odoo. Danh sách sản phẩm cuộn nội bộ, header và footer cố định.
- **Responsive**: Camera container cao `160px` trên mobile, mở rộng `240px` trên desktop (≥ 992px).

## 2.9. Nút gạt phân quyền (Chế độ kép)

Tham số `hlv_barcode_use_independent_permissions` cho phép chuyển đổi nguồn phân quyền:

| Giá trị | Hành vi |
|---------|---------|
| `False` (mặc định) | Dùng chung phân quyền từ module `hlv_warehouse_permission` (model `warehouse.user.permission`) |
| `True` | Dùng phân quyền riêng của module này (model `hlv.barcode.user.permission`) |

**Xử lý khi module phụ thuộc chưa cài**:
- Giao diện cài đặt dùng nút gọi Python (`action_open_warehouse_permissions`) thay vì action ID tĩnh → tránh lỗi `ParseError`.
- Backend dùng `request.env.get(model_name)` → trả `None` nếu module chưa cài, không crash.

## 2.10. Hướng dẫn mở rộng

| Mục đích | Cách thực hiện |
|----------|----------------|
| Thêm loại mã vạch mới | Bổ sung logic tìm kiếm vào hàm `smart_scan` trong `controllers/main.py` |
| Thêm component giao diện mới | Tạo thư mục trong `static/src/components/`, import vào `barcode_app.js` |
| Thêm cấu hình mới | Thêm field vào `res_config_settings.py`, cập nhật view XML và endpoint `/get_settings` |
| Thêm endpoint API mới | Thêm hàm trong `controllers/main.py` với decorator `@http.route()`, type `json` |
| Thêm loại phiếu phân quyền | Bổ sung vào `PICKING_TYPE_CODES` trong `barcode_permission.py` |






















---
```text
                       _oo0oo_
                      o8888888o
                      88" . "88
                      (| -_- |)
                      0\  =  /0
                    ___/`---'\___
                  .' \\|     |// '.
                 / \\|||  :  |||// \
                / _||||| -:- |||||- \
               |   | \\\  -  /// |   |
               | \_|  ''\---/''  |_/ |
               \  .-\__  '-'  ___/-. /
             ___'. .'  /--.--\  `. .'___
          ."" '<  `.___\_<|>_/___.' >' "".
         | | :  `- \`.;`\ _ /`;.`/ - ` : | |
         \  \ `_.   \_ __\ /__ _/   .-` /  /
     =====`-.____`.___ \_____/___.-`___.-'=====
                       `=---='
```
