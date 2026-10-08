# -*- coding: utf-8 -*-
"""Dựng dữ liệu JSON cho trang /hoi-gia-ncc của sale từ record.

Không phải util thuần (đọc record), nhưng không ghi gì và không đụng request — controller
chỉ việc gọi và trả về. Số tiền trả dạng số, trang tự định dạng theo vi-VN.
"""

from ..models.purchase_order import VENDOR_STATUS
from ..models.vendor_inquiry import CLOSE_REASONS, SALE_STATUS
from ..models.vendor_quote_line import VAT_SELECTION
from ..models.vendor_quote_utils import DATETIME_FMT, build_share_message, format_vn_number, local_date_text
from .sale_code import sale_code
from .chat_read import chat_stats, seen_markers
from .price_reuse import recent_vendor_price, reference_prices

QUOTE_STATE_LABELS = {
    "draft": "Nháp",
    "sent": "Chờ báo giá",
    "quoted": "Đã báo giá",
    "done": "Đã đóng",
    "cancel": "Đã huỷ",
}
SALE_STATUS_LABELS = dict(SALE_STATUS)
CLOSE_REASON_LABELS = dict(CLOSE_REASONS)
VENDOR_STATUS_LABELS = dict(VENDOR_STATUS)
VAT_LABELS = dict(VAT_SELECTION)
PRODUCT_PREVIEW = 3
CONTACT_LIMIT = 10


# Giờ Việt Nam cố định (không theo múi giờ khai ở tài khoản — tài khoản dùng chung, nhiều cái
# để trống là ra giờ UTC).
_date_text = local_date_text


def _datetime_text(value):
    return local_date_text(value, DATETIME_FMT)


def purchase_order_payload(order):
    order = order.sudo()
    chat_count, chat_unread = chat_stats(order, order.env.user)
    return {
        "chat_count": chat_count,
        "chat_unread": chat_unread,
        "id": order.id,
        "name": order.name,
        "origin": order.origin or "",
        "can_set_origin": order.state != "cancel",
        "vendor": order.partner_id.commercial_partner_id.display_name,
        "date": _date_text(order.date_approve or order.date_order),
        "amount_untaxed": order.amount_untaxed,
        "vendor_status": VENDOR_STATUS_LABELS.get(order.hlv_vendor_status, ""),
    }


def _inquiry_chat(inquiry, quotes):
    """(tổng số tin trao đổi, số tin NCC mà người đang xem chưa đọc) trên các báo giá + đơn
    mua của phiếu — để bảng phiếu báo ngay phiếu nào có tin NCC mới, và mới bao nhiêu tin."""
    records = list(quotes) + list(inquiry.purchase_order_ids.sudo())
    user = inquiry.env.user
    markers = seen_markers(records, user)
    stats = [chat_stats(record, user, markers) for record in records]
    return sum(count for count, _unread in stats), sum(unread for _count, unread in stats)


def purchase_order_detail(order):
    """Đơn mua để sale XEM (chỉ đọc): đang mua gì, của ai, bao nhiêu, đã nhận tới đâu."""
    order = order.sudo()
    state_labels = dict(order._fields["state"].selection)
    return dict(purchase_order_payload(order), **{
        "state": state_labels.get(order.state, ""),
        "date_planned": _date_text(order.date_planned),
        "amount_tax": order.amount_tax,
        "amount_total": order.amount_total,
        "lines": [
            {
                "name": line.name,
                "invoice_name": line.hlv_invoice_name or "",
                "qty": line.product_qty,
                "uom": line.product_uom.name or "",
                "qty_received": line.qty_received,
                "price_unit": line.price_unit,
                "subtotal": line.price_subtotal,
            }
            for line in order.order_line.filtered(lambda l: not l.display_type)
        ],
    })


def inquiry_summary(inquiry):
    """Một dòng trong bảng phiếu hỏi giá."""
    quotes = inquiry.quote_ids.filtered(lambda q: q.state != "cancel")
    chat_count, chat_unread = _inquiry_chat(inquiry, quotes)
    names = inquiry.line_ids[:PRODUCT_PREVIEW].mapped(lambda l: l.name or l.product_id.name)
    more = len(inquiry.line_ids) - PRODUCT_PREVIEW
    return {
        "id": inquiry.id,
        "name": inquiry.name,
        "sale_code": inquiry.sale_code or "",
        "products": ", ".join(names) + (f" và {more} sản phẩm khác" if more > 0 else ""),
        "line_count": len(inquiry.line_ids),
        "vendor_count": len(quotes),
        "quoted_count": inquiry.quoted_count,
        "chosen_count": inquiry.chosen_count,
        # Đơn bán / YCMH / đơn mua có thể thuộc sale khác hoặc sale chỉ có quyền đọc hạn
        # chế — ở đây chỉ hiện số chứng từ nên đọc bằng sudo.
        "sale_order": inquiry.sale_order_id.sudo().name or "",
        "request_name": ", ".join(inquiry.request_ids.sudo().mapped("name")),
        # Trạng thái YCMH / đơn mua hiện thành nhãn ngay ngoài danh sách (từ chối → đỏ).
        "requests": [_request_payload(r) for r in inquiry.request_ids.sudo()],
        "request_rejected": any(r.state == "rejected" for r in inquiry.request_ids.sudo()),
        "orders": [
            {"name": o.name, "vendor_status": VENDOR_STATUS_LABELS.get(o.hlv_vendor_status, "")}
            for o in inquiry.purchase_order_ids.sudo()
        ],
        "purchase_orders": inquiry.purchase_order_ids.sudo().mapped("name"),
        "close_reason": CLOSE_REASON_LABELS.get(inquiry.close_reason, ""),
        "close_note": inquiry.close_note or "",
        "deadline": _date_text(inquiry.date_deadline),
        "sale_status": inquiry.sale_status,
        "sale_status_label": SALE_STATUS_LABELS.get(inquiry.sale_status, ""),
        "chat_count": chat_count,
        "chat_unread": chat_unread,
    }


def inquiry_detail(inquiry):
    """Phiếu đầy đủ cho ngăn so sánh: NCC (cột) × sản phẩm (dòng), kèm lựa chọn."""
    quotes = inquiry.quote_ids.filtered(lambda q: q.state != "cancel").sorted("id")
    pending = inquiry.line_ids.filtered(lambda l: l.chosen_line_id and not l.request_line_id)
    data = inquiry_summary(inquiry)
    data.update({
        "note": inquiry.note or "",
        "sale_order_id": inquiry.sale_order_id.id or False,
        "purchase_orders": [purchase_order_payload(o) for o in inquiry.purchase_order_ids],
        # Đã lên YCMH vẫn chọn lại được (VD NCC báo hết hàng sau đó) — trừ dòng đã lên đơn mua.
        "can_choose": inquiry.state not in ("cancel", "closed"),
        "pending_count": len(pending),
        "can_request": inquiry.state not in ("cancel", "closed") and bool(pending),
        "can_cancel": inquiry.state == "open",
        # "Không mua": đóng phiếu, giá NCC vẫn giữ cho phiếu sau dùng lại.
        "can_close": inquiry.state == "open",
        "vendors": [_vendor_column(q) for q in quotes],
        "lines": [_compare_row(line, quotes) for line in inquiry.line_ids],
        "chosen_total": sum(inquiry.line_ids.chosen_line_id.mapped("price_subtotal")),
        "chosen_total_incl": sum(inquiry.line_ids.chosen_line_id.mapped("price_total")),
    })
    return data


def _vendor_column(quote):
    chat_count, chat_unread = chat_stats(quote, quote.env.user)
    return {
        # chat_unread: số tin NCC người đang xem chưa đọc (mốc riêng từng user).
        "chat_count": chat_count,
        "chat_unread": chat_unread,
        "quote_id": quote.id,
        "vendor_id": quote.access_id.partner_id.id,
        "name": quote.partner_id.commercial_partner_id.display_name,
        "state": quote.state,
        "state_label": QUOTE_STATE_LABELS.get(quote.state, ""),
        "submit_date": _datetime_text(quote.submit_date),
        "price_valid_until": _date_text(quote.price_valid_until),
        "price_valid": bool(quote.price_valid_until) and quote.price_valid_until >= quote._vendor_today(),
        # Mọi dòng lấy giá còn hiệu lực từ báo giá trước — không cần gửi link cho NCC.
        "reused": quote._fully_reused(),
        "amount_untaxed": quote.amount_untaxed,
        "vendor_note": quote.vendor_note or "",
        "portal_url": quote.portal_quote_url or "",
        "share_message": share_message(quote) if quote.access_id else "",
    }


def _compare_row(line, quotes):
    offers = {}
    for quote_line in line.quote_line_ids.filtered(lambda l: l.quote_id in quotes):
        offers[quote_line.quote_id.id] = {
            "line_id": quote_line.id,
            "price_unit": quote_line.price_unit,
            # NCC báo kiểu giá niêm yết − % chiết khấu (tuỳ chọn): hiện kèm để sale đối chiếu.
            "list_price": quote_line.list_price,
            "discount": quote_line.discount,
            "vat": VAT_LABELS.get(quote_line.vat, ""),
            "delivery_days": quote_line.delivery_days,
            "vendor_note": quote_line.vendor_note or "",
            "invoice_name": quote_line.invoice_name or "",
            "unavailable": quote_line.unavailable,
            "subtotal": quote_line.price_subtotal,
            # Đơn giá + thành tiền sau VAT để sale đối chiếu với giá bán (đã gồm VAT).
            "price_incl": quote_line.price_unit * (1 + quote_line.tax_rate / 100.0),
            "total_incl": quote_line.price_total,
            "is_best": quote_line.is_best_price,
            "selected": quote_line.selected,
            # Giá dùng lại từ báo giá trước (còn hiệu lực) — ghi phiếu gốc để sale biết nguồn.
            "inherited_from": _inherited_doc(quote_line.inherited_from_id),
            # NCC chưa báo mà có giá lần trước (≤ 7 ngày): chỉ để hiện "chờ xác nhận", KHÔNG phải giá.
            "reference_price": recent_vendor_price(quote_line).price_unit
            if quote_line.quote_id.state == "sent" and not quote_line.price_unit else 0,
        }
    return {
        "id": line.id,
        "product_id": line.product_id.id,
        "locked": line.locked,
        # Đã đặt một phần (NCC giao thiếu): sale chọn NCC cho phần còn lại.
        "ordered_qty": line.request_line_id.sudo().purchased_qty if line.request_line_id else 0,
        "requested_qty": line.request_line_id.sudo().product_qty if line.request_line_id else 0,
        "request_name": line.request_line_id.sudo().request_id.name or "",
        "name": line.name or line.product_id.display_name,
        "qty": line.product_qty,
        "uom": line.product_uom_id.name or "",
        "offers": offers,
    }


def _inherited_doc(source_line):
    if not source_line:
        return ""
    source = source_line.sudo()
    return source.inquiry_line_id.inquiry_id.name or source.quote_id.name


def _request_payload(request):
    """YCMH kèm trạng thái (key để tô màu, nhãn để hiện)."""
    return {
        "name": request.name,
        "state": request.state,
        "label": dict(request._fields["state"].selection).get(request.state, ""),
    }


def _reask_lines(quotes):
    """ "Tên hàng: lần trước X ₫ cho N ĐVT" cho mặt hàng NCC vừa báo trong 7 ngày (đã điền sẵn)."""
    items = []
    for quote in quotes:
        lines = {line.id: line for line in quote.line_ids}
        for line_id, reference in reference_prices(quote).items():
            line = lines[line_id]
            items.append(
                f"{line.name or line.product_id.display_name}: lần trước {format_vn_number(reference.price_unit)} ₫ "
                f"cho {format_vn_number(reference.product_qty)} {reference.product_uom_id.name or ''}".rstrip()
            )
    return items


def share_message(quotes):
    """Tin nhắn Zalo cho các báo giá cùng một NCC: nêu số báo giá, gửi link chung của NCC
    (một link cho mọi báo giá + đơn mua của họ — NCC chỉ cần lưu một link)."""
    first = quotes[:1]
    access = first.access_id
    url = access.portal_url
    deadlines = [d for d in quotes.mapped("date_deadline") if d]
    return build_share_message(
        company_name=first.company_id.name or "",
        vendor_name=access.partner_id.name or "",
        quote_names=quotes.mapped("name"),
        deadline_text=_date_text(min(deadlines)) if deadlines else "",
        url=url,
        reask=_reask_lines(quotes),
        password=access._shown_password() if access else "",
    )


def vendor_summary(partner, access, counts):
    """Một NCC ở cột trái. counts: {state báo giá: số lượng} trong phạm vi mã sale đang xem."""
    return {
        "id": partner.id,
        "name": partner.display_name,
        "waiting": counts.get("sent", 0),
        "quoted": counts.get("quoted", 0),
        "total": sum(counts.values()),
        "portal_url": access.portal_url or "",
        "password": access._shown_password() if access else "",
    }


def vendor_info(quote):
    """Thông tin NCC của một báo giá để sale liên hệ / gửi lại link: công ty, người liên hệ,
    link chung của NCC + mật khẩu, tin nhắn Zalo soạn sẵn. Đọc bằng sudo — controller đã kiểm
    báo giá thuộc phạm vi mã sale."""
    quote = quote.sudo()
    access = quote.access_id
    partner = (access.partner_id or quote.partner_id).commercial_partner_id
    contacts = partner.child_ids.filtered(lambda c: c.type == "contact" and c.active)[:CONTACT_LIMIT]
    return {
        "name": partner.display_name,
        "vat": partner.vat or "",
        "phone": partner.phone or "",
        "mobile": partner.mobile or "",
        "email": partner.email or "",
        "website": partner.website or "",
        # Chỉ ô "Đường": danh bạ NCC hay ghi cả địa chỉ đầy đủ vào đó, ghép thêm phường / tỉnh /
        # nước là lặp lại hai lần.
        "address": (partner.street or "").strip(),
        "contacts": [
            {
                "name": c.name or "",
                "function": c.function or "",
                "phone": c.mobile or c.phone or "",
                "email": c.email or "",
            }
            for c in contacts
        ],
        "portal_url": access.portal_url or "",
        "password": access._shown_password() if access else "",
        "share_message": share_message(quote) if access else "",
    }


def sale_order_summary(order):
    return {
        "id": order.id,
        "name": order.name,
        "partner": order.partner_id.display_name or "",
        "date": _date_text(order.date_order),
        "sale_code": sale_code(order.sudo()),
    }


def sale_line_payload(line):
    """Dòng đơn bán → dòng hàng trong hộp hỏi giá. Số lượng mặc định = số lượng bán."""
    product = line.product_id
    return {
        "product_id": product.id,
        "product": product.display_name,
        "name": product.display_name,
        "qty": line.product_uom_qty,
        "uom_id": line.product_uom.id,
        "uom": line.product_uom.name or "",
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
