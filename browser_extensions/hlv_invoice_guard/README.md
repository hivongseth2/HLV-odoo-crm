# HLV Invoice Guard Extension

## Cài đặt

1. Cài Odoo addon `hlv_invoice_guard`.
2. Vào Odoo Settings, app `HLV Invoice Guard`, đặt `API Token`.
3. Mở Chrome `chrome://extensions`, bật Developer mode, chọn `Load unpacked`.
4. Chọn thư mục `browser_extensions/hlv_invoice_guard`.
5. Bấm icon extension, nhập Odoo URL và API token.

## Sử dụng

Mở trang đề nghị xuất hóa đơn AMIS CRM. Khi trang có grid hàng hóa
`.body-grid.col-right.system-subform`, extension sẽ hiện panel nổi. Nhập mã đơn bán
Odoo, ví dụ `SO00123`, rồi bấm `Kiểm tra`.

Extension gửi các dòng AMIS sang:

```text
POST /api/hlv/invoice_guard/check
```

Addon Odoo tìm `sale.order.name`, sau đó tìm `purchase.order.origin` khớp mã đơn bán.
Kết quả trả về gồm `sale_order`, `purchase_order`, `issues`, và `summary`.
