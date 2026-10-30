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
| Cơ hội | `opportunity/options`, `opportunity/search`, `opportunity/lines`, `opportunity/create` (ghi), `opportunity/update` (ghi) |
| Báo giá | `quote/options`, `quote/search`, `quote/lines`, `quote/create` (ghi), `quote/create-from-opportunity` (ghi), `quote/update` (ghi) |
| Đơn hàng | `sale-order/search`, `sale-order/lines` |

Route ghi cần bật "Cho phép tạo dữ liệu trên MISA". Sửa: trường không gửi = giữ nguyên; gửi `lines`
= thay toàn bộ hàng.

## Code

- `services/`: dựng body MISA (thuần, không gọi mạng). `misa_form.py` là phần chung của form có
  bảng hàng (tính tiền, dòng, tổng, gộp dòng khi sửa); `opportunity_payload.py`, `quote_payload.py`
  theo từng form; `crm_payloads.py` cho các lệnh tìm.
- `models/`: gọi MISA theo nhóm (`crm_*.py`), đăng nhập dùng chung của misa_fetch_po_button.
- `controllers/`: route (`crm_api.py`), đọc/kiểm body (`body_fields.py`), khóa key + bật/tắt (`api_common.py`).

## Chưa có

Thêm khách hàng, tạo đơn hàng, xoá cơ hội / báo giá: chưa có request mẫu của MISA nên chưa làm
(không đoán body ghi dữ liệu thật).

Combo trong cơ hội: theo request mẫu form "Thêm Cơ hội" (30/10/2026). Báo giá dựng cùng cấu trúc —
chưa có request mẫu form Báo giá có combo.
