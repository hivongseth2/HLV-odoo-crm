# HLV Zalo ZNS sender

Module Odoo giúp:
- Xác thực OA (OAuth) để lấy access_token / refresh_token.
- Gửi ZNS khi phiếu xuất kho (stock.picking) hoàn tất (`action_done`).

## Cấu hình
1. Cài module, vào **HLV Tools → Zalo → ZNS Config**.
2. Điền `App ID`, `App Secret`, `Callback URL` (ví dụ: https://YOUR-ODOO/hlv_zalo/oauth/callback), `Template ID`.
3. Bấm **Authorize OA** để mở trang cấp quyền; sau khi đồng ý, Zalo sẽ redirect về Odoo và lưu token.
4. Khi phiếu pick hoàn thành, hệ thống sẽ gửi ZNS tới số phone của đối tác (`partner.mobile`/`partner.phone`).

> Lưu ý: Endpoint và payload ZNS có thể thay đổi theo phiên bản API của Zalo; hãy đối chiếu tài liệu chính thức để điều chỉnh `send_zns` nếu cần.
