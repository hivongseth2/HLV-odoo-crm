# -*- coding: utf-8 -*-
"""Dùng lại giá NCC đã báo khi lập phiếu hỏi giá mới — của bất kỳ sale nào.

Giá NCC báo là cam kết cho ĐÚNG số lượng đã hỏi, tới ngày hiệu lực. Chỉ được dùng lại khi
(reuse_block_reason trả ""):
- giá còn hiệu lực, NCC có báo giá (không "hết hàng");
- giá đó không còn ai ở phiếu gốc cần tới — xét THEO TỪNG GIÁ, không theo cả phiếu:
  * phiếu gốc "Không mua": mọi giá trong phiếu đều trống;
  * giá được chọn ở phiếu gốc (đang hỏi / đã lên YCMH): hàng đó đang / đã mua → không dùng;
  * giá KHÔNG được chọn: trống khi mặt hàng đó ở phiếu gốc đã lên đơn mua đủ (dòng khoá —
    sale gốc không đổi sang NCC này được nữa); trước đó vẫn là phương án dự phòng của sale
    gốc (NCC đang chọn báo hết hàng thì đổi sang) nên chưa dùng;
- chưa phiếu nào khác đang giữ giá này (đã kế thừa và phiếu đó đang hỏi / đã lên YCMH) —
  một cam kết chỉ một người dùng tại một lúc; phiếu đang giữ "Không mua" thì giá trống lại;
- là giá NCC tự báo, không phải bản kế thừa (khỏi một cam kết bị nhân thành nhiều nguồn);
- và (ở dòng mới) cùng NCC, sản phẩm, ĐVT, số lượng mới ≤ số lượng đã hỏi.
Báo giá mà mọi dòng đều kế thừa được thì coi như NCC đã báo — không cần gửi link, không báo
NCC. Đọc / ghi bằng sudo (giá của sale khác).
"""

from datetime import timedelta

from odoo import fields

REUSED_FIELDS = ("price_unit", "vat", "delivery_days", "vendor_note", "invoice_name")
# Hỏi lại cùng NCC trong chừng này ngày: điền sẵn giá NCC báo lần trước vào form của NCC
# (NCC vẫn phải bấm gửi — khác "dùng lại giá" là tự coi như NCC đã báo).
REFERENCE_DAYS = 7
HOLDING_STATES = ("open", "requested")


def _holder(source_line, exclude_line=None):
    """Dòng báo giá của phiếu khác đang giữ (kế thừa) giá này — rỗng nếu không ai giữ."""
    domain = [
        ("inherited_from_id", "=", source_line.id),
        ("inquiry_line_id.inquiry_id.state", "in", HOLDING_STATES),
    ]
    if exclude_line:
        domain.append(("id", "!=", exclude_line.id))
    return source_line.sudo().search(domain, limit=1)


def reuse_block_reason(source_line, today, exclude_line=None):
    """Lý do giá này KHÔNG dùng lại được (để hiện cho sale); dùng được → "".

    Không xét số lượng / ĐVT — cái đó phụ thuộc dòng mới (xem valid_price_line).
    """
    line = source_line.sudo()
    quote = line.quote_id
    inquiry = line.inquiry_line_id.inquiry_id
    if line.inherited_from_id:
        return "bản dùng lại của giá khác"
    if line.unavailable or line.price_unit <= 0:
        return "NCC không có hàng"
    if not quote.price_valid_until or quote.price_valid_until < today:
        return "hết hiệu lực"
    if not inquiry:
        return "giá hỏi từ YCMH, không thuộc phiếu hỏi giá"
    if inquiry.state == "cancel":
        return "phiếu gốc đã huỷ"
    if inquiry.state != "closed":
        if line.selected:
            return "phiếu gốc đã mua giá này" if line.inquiry_line_id.request_line_id else "phiếu gốc đang chọn giá này"
        if not line.inquiry_line_id.locked:
            if inquiry.state == "open":
                return "phiếu gốc chưa chốt NCC cho hàng này"
            return "phiếu gốc còn có thể đổi sang NCC này (chưa lên đơn mua)"
    holder = _holder(line, exclude_line)
    if holder:
        return "đang được %s giữ" % holder.inquiry_line_id.inquiry_id.name
    return ""


def valid_price_line(quote_line, today):
    """Giá mới nhất dùng lại được cho dòng báo giá mới: cùng NCC, sản phẩm, ĐVT, số lượng mới
    ≤ số lượng đã hỏi, và reuse_block_reason rỗng. Không có → rỗng."""
    vendor = quote_line.quote_id.partner_id.commercial_partner_id
    candidates = quote_line.sudo().search([
        ("id", "!=", quote_line.id),
        ("product_id", "=", quote_line.product_id.id),
        ("product_uom_id", "=", quote_line.product_uom_id.id),
        ("quote_id.partner_id.commercial_partner_id", "=", vendor.id),
        ("product_qty", ">=", quote_line.product_qty),
        ("inherited_from_id", "=", False),
        ("inquiry_line_id.inquiry_id.state", "!=", "cancel"),
        ("quote_id.price_valid_until", ">=", today),
        ("price_unit", ">", 0),
        ("unavailable", "=", False),
    ], order="id desc")
    for candidate in candidates:
        if not reuse_block_reason(candidate, today, exclude_line=quote_line):
            return candidate
    return candidates.browse()


def recent_vendor_price(quote_line):
    """Giá chính NCC này báo gần nhất (≤ REFERENCE_DAYS ngày) cho cùng sản phẩm, cùng ĐVT, ở báo
    giá khác — để điền sẵn khi hỏi lại. Không có → rỗng."""
    since = fields.Datetime.now() - timedelta(days=REFERENCE_DAYS)
    vendor = quote_line.quote_id.partner_id.commercial_partner_id
    return quote_line.sudo().search([
        ("quote_id", "!=", quote_line.quote_id.id),
        ("product_id", "=", quote_line.product_id.id),
        ("product_uom_id", "=", quote_line.product_uom_id.id),
        ("quote_id.partner_id.commercial_partner_id", "=", vendor.id),
        ("quote_id.state", "in", ("quoted", "done")),
        ("quote_id.submit_date", ">=", since),
        ("inherited_from_id", "=", False),
        ("price_unit", ">", 0),
        ("unavailable", "=", False),
    ], order="id desc", limit=1)


def reference_prices(quote):
    """{id dòng: dòng giá lần trước} cho các dòng CHƯA có giá của báo giá đang chờ NCC báo."""
    if quote.state != "sent":
        return {}
    references = {}
    for line in quote.line_ids.filtered(lambda l: not l.price_unit and not l.unavailable):
        reference = recent_vendor_price(line)
        if reference:
            references[line.id] = reference
    return references


def apply_valid_prices(quotes):
    """Điền giá dùng lại được vào các báo giá vừa tạo. Trả báo giá đã đủ giá (không cần gửi NCC)."""
    complete = quotes.browse()
    for quote in quotes.sudo():
        today = quote._vendor_today()
        sources = quote.line_ids.browse()
        for line in quote.line_ids:
            source = valid_price_line(line, today)
            if source:
                line.write(dict({field: source[field] for field in REUSED_FIELDS}, inherited_from_id=source.id))
                sources |= source
        if quote._fully_reused():
            quote.write({
                "state": "quoted",
                "submit_date": fields.Datetime.now(),
                # Giữ đúng cam kết của NCC: hết hạn theo giá sớm hết nhất.
                "price_valid_until": min(sources.quote_id.mapped("price_valid_until")),
            })
            complete |= quote
    return complete
