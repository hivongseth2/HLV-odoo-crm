# HLV Tracking AfterShip (Odoo 18)

Theo hướng A: dùng AfterShip để tracking **J&T Express Việt Nam** (`slug: jtexpress-vn`).  
Module này:
- Thêm trường tracking vào Delivery Order (stock.picking)
- Nút "Register Tracking (AfterShip)" để tạo tracking lần đầu
- Nút "Refresh Tracking" hoặc Cron 1h/lần để cập nhật
- (Tuỳ chọn) Webhook `/aftership/webhook?token=...` để nhận realtime

## Cài đặt
1. Upload & Install module.
2. System Parameters:
   - `aftership.api_key` = YOUR_AFTERSHIP_API_KEY
   - (optional) `aftership.webhook_token` = any-secret-string (nếu dùng webhook)
3. Trên Delivery Order:
   - Điền `Tracking Number` J&T
   - Bấm `Register Tracking (AfterShip)`

## Webhook (tuỳ chọn)
- Cấu hình webhook trong AfterShip trỏ đến: `https://YOUR_DOMAIN/aftership/webhook?token=YOUR_TOKEN`
- Đặt `aftership.webhook_token=YOUR_TOKEN` trong System Parameters.

## Ghi chú
- Cron: "AfterShip: Refresh Tracking" 1h/lần.
- Chỉ tracking, không tạo đơn vận chuyển.