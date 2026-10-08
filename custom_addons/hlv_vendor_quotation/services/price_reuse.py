# -*- coding: utf-8 -*-
"""Dùng lại giá NCC còn hiệu lực khi lập phiếu hỏi giá mới — của bất kỳ sale nào.

Phiếu cũ đóng "Không mua" nhưng giá NCC báo vẫn là cam kết của NCC tới ngày hiệu lực. Phiếu
mới gửi cùng NCC, cùng sản phẩm, cùng ĐVT thì điền sẵn giá đó (đánh dấu kế thừa); báo giá
mà mọi dòng đều có giá kế thừa thì coi như NCC đã báo — không cần gửi link, không báo NCC.
Ghi bằng sudo (sale không có quyền trên báo giá của sale khác).
"""

from odoo import fields

REUSED_FIELDS = ("price_unit", "vat", "delivery_days", "vendor_note", "invoice_name")


def valid_price_line(quote_line, today):
    """Dòng báo giá mới nhất của cùng NCC, sản phẩm, ĐVT, giá còn hiệu lực tới today. Không có → rỗng."""
    vendor = quote_line.quote_id.partner_id.commercial_partner_id
    return quote_line.sudo().search([
        ("id", "!=", quote_line.id),
        ("product_id", "=", quote_line.product_id.id),
        ("product_uom_id", "=", quote_line.product_uom_id.id),
        ("quote_id.partner_id.commercial_partner_id", "=", vendor.id),
        ("quote_id.state", "in", ("quoted", "done")),
        ("quote_id.price_valid_until", ">=", today),
        ("price_unit", ">", 0),
        ("unavailable", "=", False),
    ], order="id desc", limit=1)


def apply_valid_prices(quotes):
    """Điền giá còn hiệu lực vào các báo giá vừa tạo. Trả báo giá đã đủ giá (không cần gửi NCC)."""
    complete = quotes.browse()
    for quote in quotes.sudo():
        today = quote._vendor_today()
        sources = quote.line_ids.browse()
        for line in quote.line_ids:
            source = valid_price_line(line, today)
            if source:
                line.write(dict({field: source[field] for field in REUSED_FIELDS}, inherited_from_id=source.id))
                sources |= source
        if sources and len(sources) == len(quote.line_ids):
            quote.write({
                "state": "quoted",
                "submit_date": fields.Datetime.now(),
                # Giữ đúng cam kết của NCC: hết hạn theo giá sớm hết nhất.
                "price_valid_until": min(sources.quote_id.mapped("price_valid_until")),
            })
            complete |= quote
    return complete
