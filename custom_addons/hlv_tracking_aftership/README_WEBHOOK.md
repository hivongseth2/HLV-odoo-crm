# Hướng dẫn cấu hình Webhook AfterShip

## Tổng quan

Module đã được nâng cấp với kiến trúc mới:
- **Website tra cứu**: Lấy dữ liệu từ database Odoo (KHÔNG gọi API AfterShip)
- **Webhook**: AfterShip tự động gửi cập nhật đến Odoo khi trạng thái thay đổi
- **Kết quả**: Tiết kiệm 90-99% API calls, cập nhật real-time

## Cách hoạt động

```
┌─────────┐         ┌──────────────┐
│ Website │ ──────→ │ Odoo DB      │
│         │         │ (tracking_   │
│         │         │  payload)    │
└─────────┘         └──────┬───────┘
                           ↑
                    ┌──────┴───────┐
                    │ AfterShip    │
                    │ Webhook      │
                    └──────────────┘
```

## Cấu hình System Parameters trong Odoo

Vào **Settings → Technical → Parameters → System Parameters** và thêm:

### 1. API Key (BẮT BUỘC)
```
Key: aftership.api_key
Value: <your-aftership-api-key>
```

### 2. Webhook URL (TỰ ĐỘNG)
```
Key: web.base.url
Value: https://yourdomain.com
```
(Odoo thường tự động set, kiểm tra để đảm bảo đúng domain)

### 3. Bật Webhook (OPTIONAL)
```
Key: aftership.webhook_enabled
Value: true
```
Mặc định là `false`. Set `true` để tự động đăng ký webhook khi tạo tracking.

### 4. Webhook Secret (OPTIONAL - Bảo mật)
```
Key: aftership.webhook_secret
Value: <your-secret-key>
```
Dùng để verify webhook từ AfterShip (nâng cao).

## Cách sử dụng

### A. Đăng ký tracking và webhook

1. **Tự động** (khuyến nghị):
   - Khi tạo/cập nhật tracking number trong Odoo
   - Hệ thống tự động đăng ký với AfterShip
   - Webhook tự động được đăng ký (nếu `aftership.webhook_enabled = true`)

2. **Thủ công**:
   - Mở Stock Picking hoặc Sale Order
   - Nhập tracking number
   - Nhấn nút "Register Tracking AfterShip"

### B. Tra cứu trên website

1. Truy cập: `https://yourdomain.com/track`
2. Nhập mã vận đơn hoặc mã đơn hàng
3. **Lần đầu**: Hệ thống gọi API để lấy dữ liệu và lưu vào database
4. **Lần sau**: Dữ liệu được lấy từ database (0 API calls)
5. **Làm mới**: Nhấn nút "Làm mới trạng thái" để cập nhật từ AfterShip

### C. Webhook tự động cập nhật

Khi AfterShip có cập nhật:
- AfterShip gửi webhook đến: `https://yourdomain.com/aftership/webhook`
- Odoo tự động cập nhật `tracking_payload` và `tracking_status`
- Lần tra cứu tiếp theo sẽ thấy dữ liệu mới (không cần làm mới)

## Kiểm tra webhook

### 1. Kiểm tra webhook đã đăng ký chưa

```python
# Trong Odoo shell hoặc tạo action
client = env['stock.picking']._aftership_client()
webhooks = client.list_webhooks()
print(webhooks)
```

### 2. Test webhook endpoint

Gửi POST request đến: `https://yourdomain.com/aftership/webhook`

Payload mẫu:
```json
{
  "msg": {
    "tracking_number": "JTXXX123456",
    "slug": "jtexpress-vn",
    "tag": "InTransit",
    "checkpoints": [
      {
        "tag": "InTransit",
        "message": "Đang vận chuyển",
        "checkpoint_time": "2025-10-28T10:30:00"
      }
    ]
  }
}
```

### 3. Kiểm tra log

Mở Odoo log và tìm:
```
[hlv_tracking_aftership.controllers.webhook] Received AfterShip webhook
[hlv_tracking_aftership.controllers.webhook] Updated tracking for picking XXX
```

## Đăng ký webhook thủ công (nếu cần)

Nếu webhook chưa tự động đăng ký, chạy trong Odoo shell:

```python
# Lấy một picking bất kỳ
pick = env['stock.picking'].search([('tracking_number', '!=', False)], limit=1)

# Đăng ký webhook
pick._ensure_webhook_registered()

# Hoặc gọi trực tiếp
client = pick._aftership_client()
base_url = env['ir.config_parameter'].sudo().get_param('web.base.url')
webhook_url = f"{base_url}/aftership/webhook"
result = client.register_webhook(webhook_url)
print(result)
```

## Lưu ý

### 1. Firewall/HTTPS
- Webhook endpoint phải accessible từ internet
- AfterShip yêu cầu HTTPS (không chấp nhận HTTP)
- Nếu test local, dùng ngrok hoặc cloudflare tunnel

### 2. Rate Limit
- Với kiến trúc mới, số API calls giảm 90-99%
- Chỉ gọi API khi:
  - Đăng ký tracking lần đầu
  - Người dùng nhấn "Làm mới"
- Webhook tự động cập nhật (0 API calls)

### 3. Debugging
- Kiểm tra `tracking_payload` trong Odoo để xem dữ liệu
- Kiểm tra `tracking_last_update` để biết lần cập nhật cuối
- Set `aftership.webhook_enabled = false` để tắt webhook tạm thời

## Troubleshooting

### Webhook không hoạt động
1. Kiểm tra `web.base.url` đúng domain
2. Kiểm tra firewall cho phép POST đến `/aftership/webhook`
3. Kiểm tra HTTPS certificate hợp lệ
4. Xem log Odoo để tìm lỗi

### Dữ liệu không cập nhật
1. Kiểm tra webhook đã đăng ký: `aftership.webhook_registered = true`
2. Test webhook endpoint bằng Postman/curl
3. Kiểm tra log Odoo khi AfterShip gửi webhook

### API calls vẫn cao
1. Đảm bảo `tracking_payload` đã được lưu trong database
2. Kiểm tra web controller đang dùng dữ liệu từ cache
3. Xem trong template có biến `from_cache = True` không

## Kết quả mong đợi

### Trước khi nâng cấp
```
1000 đơn hàng × 10 lần tra cứu/ngày = 10,000 API calls/ngày
```

### Sau khi nâng cấp (với webhook)
```
1000 đơn hàng × 1 lần đăng ký = 1,000 API calls (1 lần duy nhất)
10,000 lần tra cứu = 0 API calls (lấy từ database)
Webhook tự động cập nhật = 0 API calls
```

**Tiết kiệm: 99% API calls!**
