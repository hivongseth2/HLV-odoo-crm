# Tài liệu Kỹ thuật: Module `return_sale_request`

> **Phiên bản**: 18.0.1.0.0  
> **Cập nhật lần cuối**: 2026-04-08  
> **Phụ thuộc**: `stock`, `sale`, `purchase`, `mail`, `misa_fetch_po_button`

---

## 1. Mục đích

Module quản lý quy trình **Đề nghị trả hàng bán** (khách hàng trả hàng về):

1. **Tạo và quản lý** đề nghị trả hàng thủ công trong Odoo
2. **Đồng bộ tự động** từ MISA CRM qua Wizard hoặc API webhook
3. **Gửi thông báo Zalo** cho kho khi đề nghị được xác nhận (Done)
4. **Liên kết** với Sale Order gốc và Purchase Order (NCC) để tra cứu nhanh

> **Lưu ý thiết kế hiện tại**: Tính năng **tự động tạo phiếu kho** (Stock Picking nhập/xuất) đã bị tắt (comment) để tránh ảnh hưởng luồng xuất Excel/MISA. Đề nghị khi xác nhận chuyển thẳng sang `done` mà **không** tạo phiếu kho.

---

## 2. Cấu trúc thư mục

```
return_sale_request/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── return_sale_request.py       # Model chính: return.sale.request
│   ├── return_sale_request_line.py  # Model dòng: return.sale.request.line
│   ├── sale_order.py                # Kế thừa sale.order: thêm smart button
│   ├── purchase_order.py            # Kế thừa purchase.order: thêm smart button
│   └── stock_picking.py             # Kế thừa stock.picking: auto-transition (hiện không dùng)
├── controllers/
│   ├── __init__.py
│   └── misa_return_sale_api.py      # REST API webhook: POST /api/misa/return_sale/sync
├── wizard/
│   ├── __init__.py
│   └── misa_return_sale_sync_wizard.py  # Wizard đồng bộ hàng loạt từ MISA
├── data/
│   └── return_sale_request_sequence.xml # Sequence RSR/YYYY/XXXX
├── security/
│   ├── return_sale_request_security.xml
│   └── ir.model.access.csv
├── static/
└── views/
    ├── return_sale_request_views.xml
    ├── return_sale_request_actions.xml
    ├── sale_purchase_link_views.xml
    ├── menu_views.xml
    └── (wizard views)
```

---

## 3. States (Trạng thái)

```
draft  →  done       (button_submit: xác nhận + gửi Zalo)
draft  →  rejected   (button_reject: từ chối)
done   →  draft      (button_draft: đặt lại - chỉ khi cần)
```

> Các trạng thái trung gian `return_sale` và `return_purchase` đã được comment lại cùng với quy trình phiếu kho.

---

## 4. Chi tiết từng file trong `models/`

### 4.1 `models/return_sale_request.py` — `return.sale.request`

Model chính. Chứa toàn bộ workflow, sync MISA, và thông báo Zalo.

**Fields quan trọng:**

| Field | Loại | Mô tả |
|---|---|---|
| `name` | Char | Mã đề nghị (sequence RSR/... hoặc mã MISA như `DNTL0000537`) |
| `state` | Selection | `draft` / `done` / `rejected` |
| `sale_order_id` | Many2one → `sale.order` | Đơn hàng gốc |
| `partner_id` | Many2one → `res.partner` | Khách hàng |
| `warehouse_id` | Many2one → `stock.warehouse` | Tính từ picking xuất của SO gốc |
| `purchase_order_id` | Many2one → `purchase.order` | Tính từ `origin` của PO chứa tên SO |
| `vendor_id` | Many2one → `res.partner` | Lấy từ PO |
| `misa_id` | Integer | ID nội bộ trên MISA CRM |
| `line_ids` | One2many → `return.sale.request.line` | Danh sách sản phẩm |
| `total_amount` | Monetary | Tổng tiền (từ lines hoặc `misa_summary_total`) |
| `return_reason` | Text | Lý do trả hàng |

**Computed fields:**

| Field | Logic |
|---|---|
| `warehouse_id` | Lấy từ `picking_type_id.warehouse_id` của picking **outgoing** đầu tiên của SO gốc. Fallback: kho đầu tiên trong hệ thống. |
| `purchase_order_id` | Tìm PO có `origin ilike` tên SO gốc |
| `total_amount` | Nếu `use_misa_summary_total = True` → dùng `misa_summary_total`, ngược lại sum `line_ids.line_total` |

**Workflow actions:**

| Method | Mô tả |
|---|---|
| `button_submit()` | Chuyển sang `done`, sau đó gọi `_send_zns_notification()` |
| `button_reject()` | Chuyển sang `rejected` |
| `button_draft()` | Đặt lại về `draft` |

**Thông báo Zalo:**

| Method | Mô tả |
|---|---|
| `_send_zns_notification()` | Lấy config Zalo, xác định recipients theo `warehouse_code` qua `incoming_warehouse_mapping_text`, gửi tin nhắn. Lỗi không block workflow. |
| `_format_zns_return_message()` | Build nội dung: mã đề nghị, ngày, SO gốc, khách hàng, kho, danh sách SP, lý do |

**Sync MISA (API methods):**

| Method | Mô tả |
|---|---|
| `api_sync_by_code(return_sale_code)` | Entry point: tìm theo mã ở Grid API → fetch detail → upsert |
| `_sync_from_misa_detail(misa_id, headers, grid_data)` | Fetch FormDataNew + DataSubPaging, tạo hoặc cập nhật record |
| `_fetch_lines_datasubpaging(misa_id, headers)` | Fetch dòng sản phẩm có giá từ DataSubPaging API (phân trang) |
| `_sync_lines_from_misa_data(line_data, summary_data)` | Xóa lines cũ, tạo lại từ dữ liệu DataSubPaging |
| `_sync_lines_from_misa(product_codes_text, detail_data)` | Fallback: tạo lines từ danh sách mã SP (không có giá chính xác) |
| `_set_total_from_summary(summary_data)` | Lưu tổng tiền từ SummaryData vào `misa_summary_total` |

---

### 4.2 `models/return_sale_request_line.py` — `return.sale.request.line`

| Field | Loại | Mô tả |
|---|---|---|
| `product_id` | Many2one → `product.product` | Sản phẩm |
| `product_qty` | Float | Số lượng trả |
| `return_to_vendor_qty` | Float | Số lượng trả lại NCC (dùng khi quy trình phiếu kho được bật lại) |
| `product_uom_id` | Many2one → `uom.uom` | Related từ `product_id.uom_id` |
| `unit_price` | Float | Đơn giá |
| `subtotal` | Monetary | Thành tiền trước thuế |
| `line_total` | Monetary | Tổng tiền sau thuế |

---

### 4.3 `models/sale_order.py` — kế thừa `sale.order`

Thêm:
- `return_sale_request_ids`: One2many về `return.sale.request`
- `return_sale_request_count`: Computed, hiển thị số đề nghị
- `action_view_return_sale_requests()`: Mở list/form đề nghị của SO đó

---

### 4.4 `models/purchase_order.py` — kế thừa `purchase.order`

Tương tự `sale_order.py`: thêm smart button xem đề nghị trả hàng liên quan đến PO.

---

### 4.5 `models/stock_picking.py` — kế thừa `stock.picking`

Override `_action_done()` để tự động trigger `_process_after_incoming_done()` và `_process_after_outgoing_done()` khi picking hoàn thành.

> **Lưu ý**: Hiện tại cả hai phương thức trên đều là `pass` (đã comment logic). File này giữ lại để sẵn sàng tái kích hoạt khi cần.

---

## 5. Controller

### `controllers/misa_return_sale_api.py`

**Endpoint**: `POST /api/misa/return_sale/sync`  
**Auth**: Token trong body (`token`) hoặc header `X-MISA-Token`  
**Token mặc định**: `ir.config_parameter` key `misa.api.token` (fallback: `hoanglongvu`)

**Request body:**
```json
{
  "token": "hoanglongvu",
  "return_sale_code": "DNTL0000537",
  "create_when_missing": true
}
```

**Response:**
```json
{
  "ok": true,
  "res_id": 123,
  "name": "DNTL0000537",
  "action": "created"
}
```

Gọi thẳng vào `return.sale.request.api_sync_by_code()` dưới quyền admin.

---

## 6. Wizard

### `wizard/misa_return_sale_sync_wizard.py` — `misa.return.sale.sync.wizard`

Đồng bộ hàng loạt đề nghị từ MISA theo khoảng ngày.

**Fields:**

| Field | Mô tả |
|---|---|
| `from_date` | Ngày bắt đầu lọc (mặc định: 7 ngày trước) |
| `to_date` | Ngày kết thúc lọc (mặc định: hôm nay) |
| `log_text` | Kết quả chi tiết từng bước (readonly) |
| `state` | `draft` / `done` |

**Actions:**

| Method | Mô tả |
|---|---|
| `action_sync()` | Gọi Grid API phân trang, filter ngày phía client, fetch detail + lines cho từng record, upsert vào Odoo |
| `action_reset()` | Xóa log, về `draft` để chạy lại |
| `_fetch_detail(misa_id, headers)` | Gọi FormDataNew API lấy chi tiết 1 record |
| `_fetch_lines(misa_id, headers)` | Delegate sang `return.sale.request._fetch_lines_datasubpaging()` |

**Nguồn dữ liệu line (ưu tiên giảm dần):**

1. **DataSubPaging** — có đủ qty, đơn giá, thành tiền
2. **DetailData** (FormDataNew) — dùng khi DataSubPaging rỗng, chỉ khi có trường giá
3. **product_codes_text** (ListProductIDText) — fallback cuối, không có giá chính xác

---

## 7. Tích hợp Zalo

Gửi thông báo kho khi bấm **Xác nhận** trên Đề nghị trả hàng.

**Cơ chế:**
1. Lấy `warehouse_code` từ `warehouse_id` của đề nghị
2. Tra `incoming_warehouse_mapping_text` trong `hlv.zalo.stock.notification` (config active)
3. Fallback về `incoming_recipient_user_id` nếu kho chưa có mapping
4. Gửi qua `config.send_notification_message(uid, message)`

**Mẫu tin nhắn:**
```
🔔 ĐỀ NGHỊ TRẢ HÀNG XÁC NHẬN
  • Mã đề nghị: DNTL0000537
  • Ngày: 08/04/2026
  • Đơn hàng gốc: S00123
  • Khách hàng: Nguyễn Văn A
  • Kho: TSN

📦 Sản phẩm trả:
  • [SP001] Áo thun: 3 Cái

📝 Lý do: Hàng lỗi, sai màu
```

**Lỗi gửi Zalo không block việc xác nhận đề nghị.**

---

## 8. Luồng chính

### Tạo/cập nhật từ Webhook MISA (từng đơn)

```
POST /api/misa/return_sale/sync
  → MisaApiReturnSale.api_misa_return_sale_sync()
  → return.sale.request.api_sync_by_code(return_sale_code)
      → Grid API: tìm misa_id theo code (Safety check: verify code trả về)
      → _sync_from_misa_detail(misa_id, headers, grid_data)
          → FormDataNew API: lấy detail + DetailData lines
          → _fetch_lines_datasubpaging(): lấy lines có giá (phân trang)
          → upsert record + _sync_lines_from_misa_data()
          → _auto_start_processing() → state = "done"
```

### Đồng bộ hàng loạt từ Wizard

```
Wizard.action_sync()
  → MISA CRM login (misa.api.utils)
  → Grid API (phân trang, sort by ModifiedDate)
  → [mỗi record trong khoảng ngày]:
      → _fetch_detail()        ← FormDataNew
      → _fetch_lines()         ← DataSubPaging (delegate về model)
      → upsert + _sync_lines_from_misa_data()
      → _auto_start_processing()
```

### Xác nhận thủ công từ UI

```
button_submit()
  → write(state = "done")
  → _send_zns_notification()
      → hlv.zalo.stock.notification._get_active_config()
      → get_recipients_for_incoming_warehouse(warehouse_code)
      → config.send_notification_message(uid, message)
```

---

## 9. Hướng dẫn mở rộng

### Bật lại quy trình phiếu kho
1. Uncomment `_create_incoming_picking()` và `_create_outgoing_picking()` trong `return_sale_request.py`
2. Uncomment `_process_after_incoming_done()` và `_process_after_outgoing_done()`
3. Uncomment các states `return_sale`, `return_purchase` trong `_STATES`
4. `stock_picking.py` sẽ tự hoạt động lại vì `_action_done()` đã gọi sẵn

### Thêm trường đồng bộ từ MISA
1. Thêm field vào `return_sale_request.py`
2. Map từ key MISA tương ứng trong `_sync_from_misa_detail()` (dict `vals`)
3. Nếu field có trong Wizard sync, cập nhật thêm trong `action_sync()` của wizard

### Thêm endpoint MISA mới
1. Thêm hàm vào `misa_return_sale_api.py` hoặc tạo controller riêng
2. Gọi method trên model `return.sale.request` — không xử lý HTTP trong model

### Thay đổi nội dung thông báo Zalo
Chỉnh sửa `_format_zns_return_message()` trong `return_sale_request.py`.
