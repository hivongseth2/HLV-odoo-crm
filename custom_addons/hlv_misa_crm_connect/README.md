# API MISA CRM của Odoo HLV

Odoo đăng nhập MISA CRM thay bên gọi. Bên gọi chỉ cần **API key**, không cầm tài khoản hay token MISA.

## Ở đâu

App **MISA CRM API** (icon riêng trên trang chủ Odoo). Chỉ người có quyền **Quản lý API MISA CRM**
thấy app (Cài đặt → Người dùng → tab Quyền truy cập → nhóm "MISA CRM API"). Admin có sẵn quyền.

- **Hướng dẫn API**: mỗi endpoint một trang — header, bảng tham số, payload mẫu, response mẫu,
  lệnh curl đã điền URL Odoo và key hiện tại để copy chạy thử. Nội dung nằm ở `data/api_docs.xml`
  (sửa endpoint thì sửa luôn file này).
- **Cấu hình**: bật/tắt API (mặc định TẮT), cho phép tạo dữ liệu trên MISA, tạo key mới.

## Route

Mọi route `POST /api/misa-crm/...`, body JSON, header `X-API-Key`.

| Nhóm | Route |
|---|---|
| Chung | `ping` |
| Khách hàng | `account/search`, `account/get` |
| Hàng hóa | `product/search`, `product/prices` |
| Cơ hội | `opportunity/options`, `opportunity/search`, `opportunity/lines`, `opportunity/create` (ghi) |
| Báo giá | `quote/search`, `quote/lines` |
| Đơn hàng | `sale-order/search`, `sale-order/lines` |

## Chưa có

Thêm khách hàng, tạo báo giá, tạo đơn hàng: chưa có request mẫu của MISA nên chưa làm (không đoán
body ghi dữ liệu thật). Combo trong cơ hội chưa hỗ trợ.
