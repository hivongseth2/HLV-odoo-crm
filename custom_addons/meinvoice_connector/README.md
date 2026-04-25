# MEinvoice Connector – Odoo 18

Kết nối Odoo 18 với hệ thống hóa đơn điện tử **MISA MEinvoice** (meinvoice.vn).

---

## Tính năng

| Tính năng | Mô tả |
|-----------|-------|
| 🚀 Phát hành HĐĐT | Gửi hóa đơn từ Odoo lên MEinvoice, nhận Transaction ID |
| 🔍 Tra cứu trạng thái | Kiểm tra trạng thái hóa đơn trên hệ thống MEinvoice |
| 🚫 Hủy hóa đơn | Hủy HĐĐT với lý do, cập nhật trạng thái về Đã hủy |
| ✏️ Điều chỉnh | Điều chỉnh tăng / giảm / thay thế hóa đơn |
| ⬇️ Tải PDF / XML | Tải file hóa đơn và lưu tự động vào Odoo Attachment |
| 📋 Lịch sử API | Ghi log toàn bộ lời gọi API để tra cứu và debug |
| 🔄 Tự động phát hành | Tuỳ chọn phát hành ngay khi xác nhận hóa đơn trong Odoo |

---

## Yêu cầu

- Odoo **18.0**
- Python package: `requests` (thường đã có sẵn trong Odoo)
- Tài khoản **MISA MEinvoice** với App ID (liên hệ MISA để đăng ký tích hợp)

---

## Cài đặt

1. Copy thư mục `meinvoice_connector` vào `addons/` của Odoo.
2. Vào **Cài đặt → Kỹ thuật → Cập nhật danh sách ứng dụng**.
3. Tìm `MEinvoice Connector` và nhấn **Cài đặt**.

---

## Cấu hình

Vào **Cài đặt → MEinvoice** và điền:

| Trường | Mô tả |
|--------|-------|
| Môi trường | `sandbox` khi test, `production` khi đi live |
| App ID | Chuỗi ký tự MISA cung cấp |
| Mã số thuế | MST của doanh nghiệp |
| Tài khoản | Email hoặc SĐT đăng nhập MEinvoice |
| Mật khẩu | Mật khẩu đăng nhập MEinvoice |
| Ký hiệu hóa đơn | Ví dụ: `1K24TAA` |

Nhấn **Kiểm tra kết nối** để xác nhận thông tin đúng.

---

## Sử dụng

### Phát hành hóa đơn

1. Mở hóa đơn bán hàng đã **Xác nhận** (`state = posted`).
2. Vào tab **Hóa Đơn Điện Tử (MEinvoice)**.
3. Nhấn **🚀 Phát hành HĐĐT**.
4. Hệ thống gửi hóa đơn lên MEinvoice và lưu **Transaction ID**.

### Hủy hóa đơn

1. Trên hóa đơn đã phát hành, nhấn **🚫 Hủy HĐĐT**.
2. Nhập lý do hủy → **Xác nhận Hủy**.

### Điều chỉnh hóa đơn

1. Nhấn **✏️ Điều chỉnh HĐĐT**.
2. Chọn loại điều chỉnh (tăng / giảm / thay thế).
3. Chọn hóa đơn Odoo mới (nếu có) → **Xác nhận Điều Chỉnh**.

### Tải file

- **⬇️ Tải PDF** / **⬇️ Tải XML**: Tải file từ MEinvoice, lưu vào Attachments của hóa đơn.

---

## Cấu trúc module

```
meinvoice_connector/
├── __manifest__.py
├── __init__.py
├── models/
│   ├── meinvoice_api.py       ← Toàn bộ logic gọi REST API
│   ├── account_move.py        ← Extend hóa đơn Odoo
│   ├── meinvoice_log.py       ← Model lưu lịch sử API
│   └── res_config_settings.py ← Cấu hình
├── wizard/
│   ├── meinvoice_cancel_wizard.py   ← Wizard hủy
│   └── meinvoice_adjust_wizard.py   ← Wizard điều chỉnh
├── views/
│   ├── account_move_views.xml
│   ├── meinvoice_log_views.xml
│   ├── res_config_settings_views.xml
│   └── wizard/
├── security/
│   └── ir.model.access.csv
└── data/
    └── meinvoice_data.xml
```

---

## API Endpoints sử dụng

| Chức năng | Endpoint |
|-----------|----------|
| Lấy token | `POST /itg/auth/token` |
| Phát hành | `POST /code/itg/invoice-calculating/invoiceandpublish` |
| Hủy | `POST /itg/invoicepublished/cancel` |
| Điều chỉnh | `POST /itg/invoicepublished/adjust` |
| Tra cứu | `GET /itg/invoicepublished/getinvoices` |
| Tải file | `POST /itg/invoicepublished/downloadinvoice` |

Base URL:
- **Sandbox:** `https://testapi.meinvoice.vn/api/v3`
- **Production:** `https://api.meinvoice.vn/api/v3`

---

## Lưu ý quan trọng

- **Ký số:** Module này dùng endpoint phát hành **không cần ký số riêng** (phù hợp hóa đơn khởi tạo từ hệ thống tích hợp). Nếu doanh nghiệp dùng ký số USB Token, cần tích hợp thêm bước ký (liên hệ MISA để lấy tool SignService).
- **Token:** Được cache tự động, tự refresh trước khi hết hạn 5 phút.
- **Ký hiệu hóa đơn:** Phải đúng với ký hiệu đã đăng ký trên MEinvoice. Sai ký hiệu sẽ bị từ chối.

---

## Hỗ trợ

- Tài liệu API MEinvoice: https://doc.meinvoice.vn/api/
- Hotline MISA: 1900 3.55 (trong giờ hành chính)
