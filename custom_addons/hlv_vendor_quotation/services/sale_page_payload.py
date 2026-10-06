# -*- coding: utf-8 -*-
"""Dựng dữ liệu JSON cho trang /hoi-gia-ncc của sale từ record.

Không phải util thuần (đọc record), nhưng không ghi gì và không đụng request — controller
chỉ việc gọi và trả về. Số tiền trả dạng số, trang tự định dạng theo vi-VN.
"""

from odoo import fields

from ..models.vendor_quote_line import VAT_SELECTION
from ..models.vendor_quote_utils import build_share_message

STATE_LABELS = {
    "draft": "Nháp",
    "sent": "Chờ NCC báo giá",
    "quoted": "NCC đã báo giá",
    "done": "Đã đóng",
    "cancel": "Đã huỷ",
}
VAT_LABELS = dict(VAT_SELECTION)
DATE_FMT = "%d/%m/%Y"


def _date_text(value):
    return value.strftime(DATE_FMT) if value else ""


def _datetime_text(record, value):
    if not value:
        return ""
    return fields.Datetime.context_timestamp(record, value).strftime("%H:%M " + DATE_FMT)


def quote_state(quote):
    """(mã, nhãn) trạng thái sale thấy; báo giá mở mà quá hạn thì báo "Quá hạn"."""
    if quote.state in ("sent", "quoted") and quote._vendor_status() == "expired":
        return "expired", "Quá hạn — NCC không sửa được nữa"
    return quote.state, STATE_LABELS[quote.state]


def quote_summary(quote):
    state, state_label = quote_state(quote)
    lines = quote.line_ids
    return {
        "id": quote.id,
        "name": quote.name,
        "vendor_id": quote.access_id.id,
        "vendor_name": quote.partner_id.display_name or "",
        "request_name": quote.request_id.name or "",
        "origin": quote.origin or "",
        "sale_order": quote.sale_order_id.name or "",
        "user_name": quote.user_id.name or "",
        "deadline": _date_text(quote.date_deadline),
        "submit_date": _datetime_text(quote, quote.submit_date),
        "state": state,
        "state_label": state_label,
        "line_count": len(lines),
        "offered_count": len(lines.filtered(lambda l: l.price_unit and not l.unavailable)),
        "selected_count": quote.selected_line_count,
        "amount_untaxed": quote.amount_untaxed,
    }


def quote_detail(quote):
    data = quote_summary(quote)
    data.update({
        "note": quote.note or "",
        "vendor_note": quote.vendor_note or "",
        "portal_url": quote.portal_quote_url or "",
        "password": quote.portal_password or "",
        "share_message": share_message(quote) if quote.access_id else "",
        "backend_url": f"/odoo/hlv.vendor.quote/{quote.id}",
        "can_close": quote.state in ("sent", "quoted"),
        "can_reopen": quote.state == "done",
        "can_cancel": quote.state not in ("done", "cancel"),
        "lines": [_line_payload(line) for line in quote.line_ids],
    })
    return data


def _line_payload(line):
    return {
        "id": line.id,
        "product_id": line.product_id.id,
        "product": line.product_id.display_name,
        "name": line.name or "",
        "qty": line.product_qty,
        "uom": line.product_uom_id.name or "",
        "price_unit": line.price_unit,
        "vat": VAT_LABELS.get(line.vat, ""),
        "delivery_days": line.delivery_days,
        "vendor_note": line.vendor_note or "",
        "unavailable": line.unavailable,
        "subtotal": line.price_subtotal,
        "is_best": line.is_best_price,
        "selected": line.selected,
        "linked": bool(line.request_line_id),
    }


def share_message(quotes):
    """Tin nhắn Zalo cho các báo giá cùng một NCC. Một báo giá thì gửi link thẳng vào nó."""
    first = quotes[:1]
    access = first.access_id
    url = first.portal_quote_url if len(quotes) == 1 else access.portal_url
    deadlines = [d for d in quotes.mapped("date_deadline") if d]
    return build_share_message(
        company_name=first.company_id.name or "",
        vendor_name=access.partner_id.name or "",
        quote_names=quotes.mapped("name"),
        item_count=len(quotes.line_ids),
        deadline_text=_date_text(min(deadlines)) if deadlines else "",
        url=url,
        password=access.password or "",
    )


def vendor_summary(partner, access, counts):
    """Một NCC ở cột trái. access rỗng = chưa từng gửi yêu cầu (link tạo khi gửi lần đầu).
    counts: {state: số báo giá} của NCC này, đã lọc theo phạm vi sale đang xem."""
    return {
        "id": partner.id,
        "name": partner.display_name,
        "waiting": counts.get("sent", 0),
        "quoted": counts.get("quoted", 0),
        "total": sum(counts.values()),
        "portal_url": access.portal_url or "",
        "password": access.password or "",
    }


def request_summary(request):
    return {
        "id": request.id,
        "name": request.name,
        "origin": request.origin or "",
        "sale_order": request.sale_order_id.name or "",
        "requested_by": request.x_misa_requested_by or request.requested_by.name or "",
        "date": _date_text(request.date_start),
        "state": request.state,
    }


def request_line_payload(line, remaining_qty):
    return {
        "request_line_id": line.id,
        "product_id": line.product_id.id,
        "product": line.product_id.display_name,
        "name": line.name or line.product_id.display_name,
        "qty": remaining_qty,
        "uom_id": line.product_uom_id.id,
        "uom": line.product_uom_id.name or "",
    }


def product_payload(product):
    uom = product.uom_po_id or product.uom_id
    return {
        "product_id": product.id,
        "product": product.display_name,
        "name": product.display_name,
        "uom_id": uom.id,
        "uom": uom.name,
        "qty": 1,
    }


def suggestion_payload(item, products):
    matched = products.filtered(lambda p: p.id in item["product_ids"])
    return {
        "partner_id": item["partner_id"],
        "matched": len(item["product_ids"]),
        "total": len(products),
        "matched_products": ", ".join(matched.mapped("display_name")),
        "order_count": item["order_count"],
        "last_date": _date_text(item["last_date"]),
        "from_pricelist": item["from_pricelist"],
    }
