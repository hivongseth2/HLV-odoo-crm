# MISA Shipping Address Batch Update Guide

## Overview
Công cụ này cho phép cập nhật hàng loạt `misa_shipping_address` cho các đơn hàng bán từ MISA CRM.

## Tiêu chí lọc SO
- **Trạng thái đơn hàng:** Draft hoặc Sale (chưa cancel)
- **Tên đơn hàng:** Loại trừ những có chứa "S0"
- **Địa chỉ giao hàng:** Mặc định bỏ qua những đơn hàng đã có địa chỉ (trừ khi bật Force Update)

## Cách sử dụng

### 1. Qua Odoo UI (Recommended)

#### Option 1a: Từ menu
Vào menu và chọn: **MISA → Update MISA Shipping Address** (hoặc tương tự)

#### Option 1b: Từ Sale Order
Mở danh sách Sale Order, chọn action hoặc wizard từ menu

### Cấu hình Wizard
- **Limit**: Số lượng SO tối đa cần xử lý (0 = không giới hạn, all orders)
- **Dry Run**: Nếu tích, sẽ preview mà không lưu vào DB
- **Force Update**: Nếu tích, sẽ cập nhật cả những SO đã có địa chỉ rồi

### Kết quả
Wizard sẽ hiển thị:
- Số lượng SO được cập nhật thành công
- Số lượng SO failed
- Chi tiết lỗi (nếu có)

---

### 2. Qua Odoo Shell (Advanced)

Để test hoặc batch process lớn từ terminal:

```bash
$ odoo shell -c /path/to/odoo.conf
```

Trong shell:

```python
# Option A: Chạy batch update manual
from custom_addons.misa_fetch_po_button.scripts.update_shipping_address_batch import ShippingAddressUpdater

misa_utils = env['misa.api.utils']
misa_config = env['misa.config']

# Authenticate với MISA
crm_token = misa_utils._fetch_login_crm_token()
misa_headers = misa_config.get_crm_header(crm_token)

# Tạo updater
updater = ShippingAddressUpdater(env, misa_headers)

# Chạy update
updater.update_sale_orders(limit=100, dry_run=True)  # limit=100, dry_run first to preview
updater.print_summary()

# Nếu OK, chạy lại mà không dry_run:
updater.update_sale_orders(limit=100, dry_run=False)
updater.print_summary()
```

---

### 3. Standalone Script (Development only)

File script: `custom_addons/misa_fetch_po_button/scripts/update_shipping_address_batch.py`

Hiện tại script không thể chạy standalone (cần Odoo environment), nhưng có thể mở rộng nếu cần.

---

## Xử lý lỗi

### Lỗi: "Failed to login to MISA CRM"
- Kiểm tra credentials trong `misa_api_utils.py` → `_fetch_login_crm_token()`
- Kiểm tra kết nối internet
- Verify MISA CRM API endpoint (`https://amisapp.misa.vn/APIS/AuthenAPI/api/Account/login`)

### Lỗi: "MISA API returned no address"
- Đơn hàng không tìm thấy trên MISA CRM
- Tên đơn hàng không khớp chính xác
- Check log để xem chi tiết

### Lỗi: "Update script not found"
- Kiểm tra file `scripts/update_shipping_address_batch.py` có tồn tại
- Ensure module được instance properly

---

## Architecture

### Files Involved

1. **Wizard Model**: `wizard/misa_shipping_address_batch_update.py`
   - TransientModel để handle UI input
   - Gọi ShippingAddressUpdater script
   
2. **Batch Update Script**: `scripts/update_shipping_address_batch.py`
   - `ShippingAddressUpdater` class: logic batch update
   - `run_from_odoo_shell()`: helper function

3. **Views**: `wizard/misa_shipping_address_batch_update_views.xml`
   - Wizard form
   - Wizard action

4. **Core Models**:
   - `models/sale_order_misa_sync.py`: field definition + resync integration
   - `models/stock_picking_crm_delivery.py`: related field for display

---

## Data Flow

```
Sale Order (Odoo)
    ↓
Wizard → get_crm_header + _fetch_login_crm_token
    ↓
ShippingAddressUpdater.update_sale_orders()
    ↓
fetch_from_misa(sale_order_name)
    ↓
MISA Grid API (POST with AISearchKeyword)
    ↓
Extract ShippingAddress from response
    ↓
sale_order.write({'misa_shipping_address': address})
    ↓
stock_picking.x_misa_shipping_address (related field auto-updated)
```

---

## Notes

- Script sử dụng MISA Grid API endpoint: `https://amisapp.misa.vn/crm/g1/api/business/SaleOrder/Grid`
- Payload được giữ nguyên từ user's original request, chỉ thay `AISearchKeyword`
- Với mỗi SO, script search 1 lần trên MISA (có thể slow nếu có 1000+ orders)
- Related field trên stock.picking sẽ tự động cập nhật khi SO field change

---

## Optimization (Future)

- Batch call MISA API instead of 1-by-1
- Cache results
- Async processing
- Add more filters (date range, account, etc.)

---

## Contact
Liên hệ dev team nếu có issue hoặc improvement suggestions.
