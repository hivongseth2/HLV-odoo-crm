# -*- coding: utf-8 -*-
"""Báo tin nhắn trao đổi theo thời gian thực qua bus (websocket) của Odoo.

Hai trang tự dựng (/bao-gia của NCC, /hoi-gia-ncc của sale) không có bộ JS backend của Odoo,
nên nói chuyện thẳng với /websocket bằng WebSocket của trình duyệt (static/src/js/odoo_bus.js).

Bẫy bảo mật: client đăng ký được BẤT KỲ kênh tên chữ nào (bus.ir_websocket không kiểm), kể cả
khách chưa đăng nhập. Nên:
- kênh của NCC đặt theo mã link bí mật của NCC — không đoán được;
- kênh của sale theo token mã sale (đoán được), nên tin trên bus CHỈ chở id / tên chứng từ —
  trang nhận tin xong tự gọi API đã kiểm quyền để lấy nội dung.
"""

from odoo.addons.bus.websocket import WebsocketConnectionHandler

BUS_TYPE = "hlv_vq_chat"
SALE_ALL_CHANNEL = "hlv_vq_sale_all"


def bus_version():
    """Version websocket worker Odoo đòi ở ?version= — lệch là server đóng kết nối ngay."""
    return WebsocketConnectionHandler._VERSION


def vendor_channel(access):
    return f"hlv_vq_vendor_{access.access_token}"


def sale_channel(env, code):
    """Kênh của một mã sale (cùng token với link ?t= của trang); code rỗng = kênh "tất cả"."""
    if not code:
        return SALE_ALL_CHANNEL
    return f"hlv_vq_sale_{env['stock.picking']._misa_invoice_saler_code_token(code)}"


def notify_chat(record, author_name, from_vendor):
    # author_name: tên công ty (vendor_chat.author_label), không phải tên tài khoản.
    """Báo có tin trao đổi mới trên báo giá / đơn mua record.

    Bên sale: kênh "tất cả" (thu mua) + kênh mã sale của các phiếu liên quan. Bên NCC: chỉ khi
    tin do sale gửi (NCC tự gửi thì trang của họ đã tự tải lại).
    """
    env = record.env
    record = record.sudo()
    is_quote = record._name == "hlv.vendor.quote"
    if is_quote:
        accesses, inquiries = record.access_id, record.inquiry_id
    else:
        accesses = env["hlv.vendor.quote.access"].sudo().search([
            ("partner_id", "=", record.partner_id.commercial_partner_id.id),
        ])
        inquiries = record.hlv_inquiry_ids
    base = {
        "model": "quote" if is_quote else "order",
        "res_id": record.id,
        "name": record.name,
        "author": author_name,
        "from_vendor": from_vendor,
    }
    notifications = [
        (channel, BUS_TYPE, dict(base, inquiry_ids=inquiries.ids))
        for channel in {SALE_ALL_CHANNEL} | {sale_channel(env, c) for c in inquiries.mapped("sale_code") if c}
    ]
    if not from_vendor:
        notifications += [(vendor_channel(access), BUS_TYPE, base) for access in accesses]
    bus = env["bus.bus"].sudo()
    for channel, notification_type, message in notifications:
        bus._sendone(channel, notification_type, message)
