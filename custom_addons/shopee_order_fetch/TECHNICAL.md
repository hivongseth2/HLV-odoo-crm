# Tài liệu Kỹ thuật: Module `shopee_order_fetch`

> **Phiên bản**: 18.0.1.0.0  
> **Cập nhật lần cuối**: 2026-03-02  
> **Phụ thuộc**: `sale`, `stock`, `sale_shopee`

---

## 1. Mục đích

Module cho phép:
1. **Lấy đơn hàng thủ công** từ Shopee API (`get_order_detail`) qua Wizard trong phân hệ Kho
2. **Tạo Sales Order** Odoo từ dữ liệu Shopee trả về
3. **Cập nhật giá Escrow** từ nút bấm trực tiếp trên form `sale.order` (chỉ hiện với đơn có `shopee_order_ref`)

---

## 2. Cấu trúc thư mục

```
shopee_order_fetch/
├── __init__.py                  # import: services, models, wizard
├── __manifest__.py
├── services/                    # ← Service layer (dùng chung cho cả wizard và model)
│   ├── __init__.py
│   ├── shopee_api.py            # Gọi API Shopee (HTTP, sign, credentials)
│   ├── shopee_escrow.py         # Xử lý giá & voucher từ escrow
│   └── shopee_order_builder.py  # Tạo đơn hàng (partner, product, order line)
├── models/
│   ├── __init__.py
│   └── sale_order.py            # Kế thừa sale.order: action cập nhật giá escrow
├── wizard/
│   ├── __init__.py
│   └── shopee_order_fetch_wizard.py  # Wizard form: fields + actions gọi services
├── security/
│   └── ir.model.access.csv
└── views/
    ├── shopee_order_fetch_wizard_views.xml  # Form wizard + menu
    └── sale_order_views.xml                 # Inherit form sale.order: thêm nút escrow
```

---

## 3. Quy tắc kiến trúc

| Nguyên tắc | Mô tả |
|---|---|
| **Logic → services/** | Mọi tính toán, gọi API, xử lý dữ liệu đều nằm trong `services/`. Wizard và model chỉ gọi xuống, không tự xử lý. |
| **Không trùng lập** | Một hàm chỉ tồn tại ở **một nơi duy nhất** trong `services/`. Không được copy hàm sang wizard hay model. |
| **Services không gọi ngược lên** | `services/*.py` không được import từ `wizard/` hay `models/`. |
| **Không hardcode credentials** | Credentials luôn lấy qua `shopee_api.get_credentials_from_shop()` hoặc `get_credentials_from_wizard()`. |

---

## 4. Chi tiết từng file trong `services/`

### 4.1 `services/shopee_api.py`

Toàn bộ giao tiếp với Shopee Open API v2.

| Hàm | Mô tả |
|---|---|
| `generate_sign(...)` | Tạo HMAC-SHA256 signature |
| `get_credentials_from_shop(shop)` | Đọc credentials từ `shopee.shop` record |
| `get_credentials_from_wizard(wizard)` | Đọc credentials từ `shopee.order.fetch.wizard` record |
| `call_order_detail(creds, order_sn_str, optional_fields)` | Gọi `GET /api/v2/order/get_order_detail`, trả `(status, body, params)` |
| `call_escrow_detail(creds, order_sn)` | Gọi `GET /api/v2/payment/get_escrow_detail`, trả `dict` hoặc `None` nếu lỗi |
| `call_escrow_detail_strict(creds, order_sn)` | Như trên nhưng raise `UserError` thay vì trả `None` |

**Khi thêm endpoint mới**: Thêm hàm tại đây. Đặt tên dạng `call_<endpoint_name>(creds, ...)`.

---

### 4.2 `services/shopee_escrow.py`

Xử lý dữ liệu escrow: cập nhật giá sản phẩm và phân bổ voucher.

| Hàm | Mô tả |
|---|---|
| `get_tax_included(env, company)` | Tìm `account.tax` có `price_include=True` phù hợp |
| `update_order_lines_from_escrow(so, escrow_data)` | Cập nhật `price_unit` + `discount` cho các dòng SP, khớp theo `model_sku`/`item_sku` ↔ `product.default_code` |
| `apply_escrow_voucher(so, escrow_data)` | Phân bổ `voucher_from_seller` vào `discount %` của các dòng. Dòng cuối nhận phần dư (tránh lỗi làm tròn). |

**Lưu ý khi sửa logic voucher**: Luôn đảm bảo dòng cuối `last_line_voucher = total - distributed` để tổng chính xác.

---

### 4.3 `services/shopee_order_builder.py`

Tạo toàn bộ `sale.order` và records liên quan từ dữ liệu Shopee.

| Hàm | Mô tả |
|---|---|
| `find_or_create_partner(env, order_data)` | Tạo/tìm `res.partner` theo `buyer_username`. Trả `(partner, delivery_address)`. |
| `find_or_create_delivery_address(env, parent, addr)` | Tạo `res.partner` type=delivery. Bỏ qua nếu tất cả field là `****`. |
| `find_or_create_shopee_item(env, item_data, shop)` | Map Shopee item → `product.product`. Thứ tự: shopee.item ID → SKU → tên → tạo mới. **Sản phẩm tạo mới** luôn có `is_storable=True` để kích hoạt theo dõi tồn kho. |
| `create_order_line(env, so, item_data, shop)` | Tạo `sale.order.line` từ item. |
| `create_order_from_data(env, order_data, shop, escrow_data)` | Orchestrator: gọi các hàm trên theo thứ tự, trả `sale.order`. |

**Kho mặc định**: `DEFAULT_WAREHOUSE_CODE = 'TSN'`. Đổi ở đây nếu cần.

**⚠️ Lưu ý khi tạo product mới**: Luôn đặt `is_storable=True` để kích hoạt theo dõi tồn kho. Nếu không, sản phẩm sẽ không xuất hiện trong các bước picking/scanning vạch khác.

---

## 5. Models kế thừa

### `models/sale_order.py` — `sale.order`

Chỉ thêm **1 action**:

```python
def action_update_price_from_escrow(self):
    """Cập nhật giá từ Escrow cho đơn hàng đang mở."""
```

Nút bấm tương ứng hiển thị trong `header` của form `sale.order`, **chỉ khi `shopee_order_ref` có giá trị** (`invisible="not shopee_order_ref"`).

**Khi thêm field mới trên `sale.order`**: Thêm vào file này, không tạo file mới dưới `models/`.

---

## 6. Wizard

### `wizard/shopee_order_fetch_wizard.py`

**Fields (production-ready)**:

| Field | Loại | Mô tả |
|---|---|---|
| `shop_id` | Many2one → `shopee.shop` | Shop Shopee để lấy credentials |
| `order_sn_list` | Text | Danh sách mã đơn (mỗi dòng 1 mã hoặc cách bằng dấu phẩy) |
| `response_optional_fields` | Char | Optional fields gửi lên API |
| `result_display` | Text (readonly) | Hiển thị kết quả sau mỗi action |

**Fields đã comment (staging/test)**:

| Field | Mô tả |
|---|---|
| `mock_json` | JSON từ `get_order_detail` để test offline |
| `mock_escrow_json` | JSON từ `get_escrow_detail` để test offline |
| `sale_order_ids` | Gán thủ công `shopee_order_ref` cho đơn Odoo đã có |

**Actions (production-ready)**:

| Action | Mô tả |
|---|---|
| `action_fetch_order` | Gọi API, hiển thị JSON kết quả. Không ghi DB. |
| `action_fetch_and_create_order` | Gọi API, tạo `sale.order` cho mỗi mã đơn tìm thấy. |

**Actions đã comment (staging/test)**:

| Action | Mô tả |
|---|---|
| `action_update_price_from_escrow` | Cập nhật giá hàng loạt từ Escrow theo danh sách mã đơn |
| `action_test_create_order` | Tạo đơn từ mock JSON không gọi API |

---

## 7. Views

### `views/shopee_order_fetch_wizard_views.xml`

- **Form wizard** `shopee.order.fetch.wizard.form`
- **Action** `action_shopee_order_fetch_wizard` (target=new)
- **Menu** dưới `stock.menu_stock_root` (Phân hệ Kho), sequence=99

### `views/sale_order_views.xml`

- Inherit `sale.view_order_form`
- Thêm field ẩn `shopee_order_ref` và nút **"Cập nhật giá Shopee"** vào `<header>`

---

## 8. Luồng chính

### Tạo đơn hàng

```
Wizard.action_fetch_and_create_order()
  → shopee_api.get_credentials_from_wizard()
  → shopee_api.call_order_detail()
  → [với mỗi order_sn]:
      → shopee_api.call_escrow_detail()          [best-effort]
      → shopee_order_builder.create_order_from_data()
          → find_or_create_partner()
          → find_or_create_shopee_item() × n     [mỗi dòng SP]
          → create_order_line() × n
          → shopee_escrow.apply_escrow_voucher()
          → sale.order.action_confirm()
```

### Cập nhật giá từ form đơn hàng

```
sale.order.action_update_price_from_escrow()
  → shopee_api.get_credentials_from_shop(order.shopee_shop_id)
  → shopee_api.call_escrow_detail_strict(creds, order.shopee_order_ref)
  → shopee_escrow.update_order_lines_from_escrow(order, escrow_data)
  → shopee_escrow.apply_escrow_voucher(order, escrow_data)
```

---

## 9. Hướng dẫn mở rộng

### Thêm endpoint Shopee mới
1. Thêm hàm `call_<tên>()` vào `services/shopee_api.py`
2. Gọi từ wizard action hoặc model action — không tự xử lý HTTP ở đó

### Thêm trường mới lên sale.order
1. Thêm `fields.*` vào `models/sale_order.py`
2. Thêm hiển thị vào `views/sale_order_views.xml`

### Thêm logic xử lý dữ liệu escrow
1. Thêm hàm vào `services/shopee_escrow.py`
2. Gọi từ `sale_order.py` hoặc wizard action

### Thêm loại order mới (ví dụ: đơn hoàn trả)
1. Thêm hàm builder vào `services/shopee_order_builder.py` nếu logic tạo đơn khác biệt
2. Thêm action vào wizard hoặc model tùy use case
