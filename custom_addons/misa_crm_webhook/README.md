# MISA AMIS CRM – Webhook Receiver (Odoo 18)

Module nhận sự kiện webhook từ **MISA AMIS CRM** và đồng bộ dữ liệu vào Odoo 18.

---

## Cài đặt

1. Copy thư mục `misa_crm_webhook` vào `addons/`.
2. **Cài đặt → Cập nhật danh sách ứng dụng** → Tìm `MISA CRM Webhook` → **Cài đặt**.

---

## Cấu hình

### Bước 1 – Lấy Webhook URL trong Odoo

Vào **Cài đặt → MISA CRM Webhook** → nhấn **📋 Xem Webhook URL**.

URL có dạng: `https://yourodoo.com/misa/crm/webhook`

### Bước 2 – Thiết lập trong AMIS CRM

1. Đăng nhập AMIS CRM → **Thiết lập** (biểu tượng bánh răng)
2. Vào **Kết nối → API**
3. Tab **Thiết lập**:
   - **AppID**: đặt tên tùy ý (ví dụ `OdooConnector`)
   - **Địa chỉ Webhook**: dán URL ở bước 1
4. Nhấn **Kết nối**

### Bước 3 – Cấu hình trong Odoo

Vào **Cài đặt → MISA CRM Webhook**:

| Field | Mô tả |
|-------|-------|
| AppID | Phải khớp với AppID đặt ở AMIS CRM |
| Secret Key | Khóa bí mật để xác thực HMAC |
| Bật xác thực chữ ký | Nên bật khi production, tắt khi debug |
| Tự động tạo khách hàng | Tạo res.partner nếu chưa tồn tại |
| Tự động tạo đơn hàng | Tạo sale.order nếu chưa tồn tại |

---

## Endpoint

| Method | URL | Mô tả |
|--------|-----|-------|
| `POST` | `/misa/crm/webhook` | Nhận webhook từ AMIS CRM |
| `GET`  | `/misa/crm/webhook` | Health check (AMIS CRM verify) |

### Headers AMIS CRM gửi kèm (tuỳ phiên bản)

```
Content-Type: application/json
X-App-Id: <AppID>
X-Signature: <HMAC-SHA256 của body>
```

---

## Sự kiện được hỗ trợ

| event_type | Hành động Odoo |
|-----------|----------------|
| `customer.created` | Tạo mới `res.partner` |
| `customer.updated` | Cập nhật `res.partner` |
| `order.created` | Tạo mới `sale.order` |
| `order.updated` | Cập nhật `sale.order` (nếu còn Draft) |
| `ping` / `test` / `verify` | Bỏ qua, ghi log `ignored` |

---

## Payload mẫu AMIS CRM gửi

### Khách hàng

```json
{
  "event_type": "customer.created",
  "app_id": "OdooConnector",
  "data": {
    "customer_id": "KH-001",
    "customer_name": "Công ty ABC",
    "phone": "0901234567",
    "email": "abc@company.vn",
    "address": "123 Lê Lợi, Q1, TP.HCM",
    "tax_code": "0123456789",
    "customer_code": "KH-001"
  }
}
```

### Đơn hàng

```json
{
  "event_type": "order.created",
  "app_id": "OdooConnector",
  "data": {
    "order_id": "DH-2024-001",
    "order_code": "DH-2024-001",
    "customer_id": "KH-001",
    "order_date": "2024-11-01T10:30:00",
    "total_amount": 5000000,
    "status": "confirmed",
    "details": [
      {
        "product_code": "SP001",
        "product_name": "Sản phẩm A",
        "quantity": 2,
        "unit_price": 1500000,
        "discount_rate": 0
      }
    ]
  }
}
```

---

## Xem log & retry

Vào **Sales → MISA CRM → Webhook Logs**:

- Lọc theo trạng thái: ✅ Thành công / ❌ Lỗi / 📥 Mới nhận
- Mở bản ghi lỗi → nhấn **🔄 Thử lại** để xử lý lại

---

## Cấu trúc module

```
misa_crm_webhook/
├── controllers/
│   └── misa_crm_webhook_controller.py  ← HTTP endpoint /misa/crm/webhook
├── models/
│   ├── misa_crm_webhook_log.py         ← Model ghi log webhook
│   ├── misa_crm_processor.py           ← Xử lý nghiệp vụ (partner / order)
│   └── res_config_settings.py          ← Cấu hình
├── views/
│   ├── res_config_settings_views.xml
│   ├── misa_crm_webhook_log_views.xml
│   └── misa_crm_menus.xml
├── security/ir.model.access.csv
├── data/misa_crm_data.xml
└── README.md
```

---

## Lưu ý

- Module commit log **ngay lập tức** trước khi xử lý, đảm bảo không mất log dù processor lỗi.
- AMIS CRM yêu cầu endpoint phải trả về **HTTP 200** nếu không sẽ retry liên tục → processor lỗi vẫn trả 200 nhưng ghi state = `error` để retry thủ công.
- Chỉ hỗ trợ **cập nhật sale.order ở trạng thái Draft** (giống quy định MISA CRM).
