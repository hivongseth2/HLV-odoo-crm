# -*- coding: utf-8 -*-
"""Dựng dữ liệu JSON cho trang /hoi-gia-ncc của sale từ record.

Không phải util thuần (đọc record), nhưng không ghi gì và không đụng request — controller
chỉ việc gọi và trả về. Số tiền trả dạng số, trang tự định dạng theo vi-VN.
"""

from ..models.purchase_order import PROGRESS_LABELS
from ..models.vendor_inquiry import CLOSE_REASONS, SALE_STATUS
from ..models.vendor_quote_line import VAT_SELECTION
from .combo_lines import kit_bom
from ..models.vendor_quote_utils import (
    DATETIME_FMT, build_share_message, format_vn_number, local_date_text, price_incl_vat,
)
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
# Tiến độ NCC hiện cạnh số đơn mua: NCC đã báo / kho đã nhận (một phần / đủ). Đơn mới (NCC chưa báo gì) thì không ghi.
VENDOR_PROGRESS_SHOWN = ("acknowledged", "packed", "shipped", "partial", "delivered")
VAT_LABELS = dict(VAT_SELECTION)
PRODUCT_PREVIEW = 3
CONTACT_LIMIT = 10


# Giờ Việt Nam cố định (không theo múi giờ khai ở tài khoản — tài khoản dùng chung, nhiều cái
# để trống là ra giờ UTC).
_date_text = local_date_text


def _datetime_text(value):
    return local_date_text(value, DATETIME_FMT)


def _vendor_progress_label(order):
    """Nhãn tiến độ NCC cạnh số đơn mua ("" khi chưa có gì để báo — chờ đóng gói / chưa xác nhận / hủy)."""
    progress = order._hlv_vendor_progress()
    return PROGRESS_LABELS.get(progress, "") if progress in VENDOR_PROGRESS_SHOWN else ""


def _order_list_payload(order):
    """Đơn mua ở bảng phiếu: tiến độ (mã → màu chip, nhãn → tooltip) + ghi chú kho (giờ hàng về thực tế)."""
    progress = order._hlv_vendor_progress()
    return {
        "name": order.name,
        "vendor_status": PROGRESS_LABELS.get(progress, "") if progress in VENDOR_PROGRESS_SHOWN else "",
        "progress": progress,
        "progress_label": PROGRESS_LABELS.get(progress, ""),
        "note": order._hlv_warehouse_note(),
    }


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
        "amount_total": order.amount_total,
        "vendor_status": _vendor_progress_label(order),
        # Giao một phần / NCC đổi ngày giao / trễ hẹn.
        "vendor_event": order.hlv_vendor_event or "",
        # Ai báo tin trên (tên NCC / bên mua / "Hệ thống") — tin hệ thống tự sinh không mặc định là NCC.
        "vendor_event_actor": order._hlv_event_actor() if order.hlv_vendor_event else "",
        # NCC gửi CPN / chành: hãng / chành + mã vận đơn / số xe — sale theo hàng giúp khách.
        "vendor_ship": order._hlv_ship_text(),
        # Ghi chú kho trên đơn (giờ / ngày hàng về thực tế).
        "warehouse_note": order._hlv_warehouse_note(),
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


def purchase_request_detail(request):
    """YCMH để sale XEM ngay trên trang (chỉ đọc): đã lên hàng gì, của NCC nào, giá nào, đã ra đơn mua chưa.
    Giá sau VAT là số chính (thói quen đọc giá của hai bên), chưa VAT đi kèm."""
    request = request.sudo()
    state_labels = dict(request._fields["state"].selection)
    lines = request.line_ids.sorted("id")
    return {
        "id": request.id,
        "name": request.name,
        "state": request.state,
        "state_label": state_labels.get(request.state, ""),
        "requester": request.x_misa_requested_by or "",
        "origin": request.origin or "",
        "date_start": _date_text(request.date_start),
        "date_wanted": _date_text(request.hlv_date_wanted),
        "picking_type": request.picking_type_id.display_name or "",
        "delivery_address": request.delivery_address or "",
        "lines": [
            {
                "name": line.name or line.product_id.display_name,
                "qty": line.product_qty,
                "uom": line.product_uom_id.name or "",
                "vendor": line.actual_supplier_id.commercial_partner_id.display_name or "",
                "price_net": line.actual_price_unit,
                "price": price_incl_vat(line.actual_price_unit, line.actual_tax_rate),
                "date_required": _date_text(line.date_required),
                "backorder": line.hlv_backorder,
                "note": line.misa_note or "",
                "cancelled": line.cancelled,
                "orders": [{"id": o.id, "name": o.name} for o in line.purchase_lines.order_id],
            }
            for line in lines
        ],
    }


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
        "opportunity_ref": inquiry.opportunity_ref or "",
        "products": ", ".join(names) + (f" và {more} sản phẩm khác" if more > 0 else ""),
        "line_count": len(inquiry.line_ids),
        "vendor_count": len(quotes),
        "quoted_count": inquiry.quoted_count,
        "chosen_count": inquiry.chosen_count,
        # Đơn bán / YCMH / đơn mua có thể thuộc sale khác hoặc sale chỉ có quyền đọc hạn
        # chế — ở đây chỉ hiện số chứng từ nên đọc bằng sudo.
        "sale_order": inquiry.sale_order_id.sudo().name or "",
        # Trạng thái YCMH / đơn mua hiện thành nhãn ngay ngoài danh sách (từ chối → đỏ).
        "requests": [_request_payload(r) for r in inquiry.request_ids.sudo()],
        "request_rejected": any(r.state == "rejected" for r in inquiry.request_ids.sudo()),
        "orders": [_order_list_payload(o) for o in inquiry.purchase_order_ids.sudo()],
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
    chosen = inquiry.line_ids.chosen_line_ids
    pending = chosen.filtered(lambda l: l._hlv_needs_request())
    data = inquiry_summary(inquiry)
    data.update({
        "note": inquiry.note or "",
        "sale_order_id": inquiry.sale_order_id.id or False,
        "purchase_orders": [purchase_order_payload(o) for o in inquiry.purchase_order_ids],
        # Đã lên YCMH vẫn chọn thêm / đổi được (VD NCC báo hết hàng, mua phần còn thiếu) — trừ phần đã lên đơn mua.
        "can_choose": inquiry.state not in ("cancel", "closed"),
        # Số sản phẩm có NCC đã chọn mà chưa lên YCMH.
        "pending_count": len(pending.inquiry_line_id),
        "can_request": inquiry.state not in ("cancel", "closed") and bool(pending),
        "can_cancel": inquiry.state == "open",
        "can_set_opportunity": inquiry.state != "cancel",
        # Ô "Hạn báo giá" sửa được khi Cài đặt bật và phiếu còn hỏi giá / đã lên YCMH.
        "can_set_deadline": inquiry.state in ("open", "requested") and inquiry._hlv_sale_can_edit_deadline(),
        "deadline_iso": inquiry.date_deadline.isoformat() if inquiry.date_deadline else "",
        "can_set_sale_code": inquiry.state != "cancel",
        # Mã đơn hàng của khách: nhập được ngay khi có YCMH, chưa cần đơn mua (models/vendor_inquiry.py).
        "order_ref": inquiry.hlv_order_ref(),
        "can_set_order_ref": inquiry.state != "cancel" and any(inquiry._hlv_order_ref_targets()),
        # Hỏi thêm NCC (NCC đã hỏi báo hết hàng…) — cả khi đã lên YCMH, còn sản phẩm chưa lên đơn mua.
        "can_add_vendor": inquiry.state in ("open", "requested") and not all(inquiry.line_ids.mapped("locked")),
        # Thêm sản phẩm vào phiếu đã gửi (trùng sản phẩm thì cộng SL) — cả khi đã lên YCMH.
        "can_add_products": inquiry.state in ("open", "requested"),
        # "Không mua": đóng phiếu, giá NCC vẫn giữ cho phiếu sau dùng lại.
        "can_close": inquiry.state == "open",
        "vendors": [_vendor_column(q) for q in quotes],
        "lines": [_compare_row(line, quotes) for line in inquiry.line_ids],
        # Tổng tiền theo SL mua của từng NCC đã chọn.
        "chosen_total": sum(line.price_unit * line.chosen_qty for line in chosen),
        "chosen_total_incl": sum(_price_incl(line) * line.chosen_qty for line in chosen),
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
        "amount_total": quote.amount_total,
        "vendor_note": quote.vendor_note or "",
        "portal_url": quote.portal_quote_url or "",
        "share_message": share_message(quote) if quote.access_id else "",
    }


def _price_incl(quote_line):
    """Đơn giá sau VAT của một dòng báo giá (rỗng → 0) — giá bên mình đọc và so."""
    return quote_line.price_unit * (1 + quote_line.tax_rate / 100.0) if quote_line else 0.0


def _compare_row(line, quotes):
    offers = {}
    for quote_line in line.quote_line_ids.filtered(lambda l: l.quote_id in quotes):
        offers[quote_line.quote_id.id] = {
            "line_id": quote_line.id,
            # Bên mua đã thu hồi món này với NCC này — bảng so giá vẽ gạch chéo "Đã thu hồi" + "Hỏi lại".
            "withdrawn": quote_line.withdrawn,
            "price_unit": quote_line.price_unit,
            # NCC báo kiểu giá niêm yết − % chiết khấu (tuỳ chọn): hiện kèm để sale đối chiếu.
            "list_price": quote_line.list_price,
            "list_price_incl": quote_line.list_price * (1 + quote_line.tax_rate / 100.0),
            "discount": quote_line.discount,
            "vat": VAT_LABELS.get(quote_line.vat, ""),
            "delivery_days": quote_line.delivery_days,
            "vendor_note": quote_line.vendor_note or "",
            "invoice_name": quote_line.invoice_name or "",
            "unavailable": quote_line.unavailable,
            # NCC không đủ SL hỏi: "có 6/10 · 4 hẹn 20/10/2026" ("" = có đủ).
            "supply": quote_line._availability_text(),
            "subtotal": quote_line.price_subtotal,
            # Đơn giá + thành tiền sau VAT để sale đối chiếu với giá bán (đã gồm VAT).
            "price_incl": _price_incl(quote_line),
            "total_incl": quote_line.price_total,
            "is_best": quote_line.is_best_price,
            "selected": quote_line.selected,
            # Chia SL giữa các NCC: SL mua của NCC này, phần đã lên đơn mua, SL tối đa NCC có (null =
            # không giới hạn), YCMH của NCC này; to_request = đã chọn mà chưa lên YCMH.
            "chosen_qty": quote_line.chosen_qty,
            "ordered_qty": quote_line._hlv_ordered_qty() if quote_line.selected else 0.0,
            "max_qty": quote_line._hlv_cap(),
            "request_names": quote_line._hlv_live_request_lines().request_id.mapped("name"),
            "to_request": quote_line._hlv_needs_request(),
            # NCC thiếu hàng: sẵn hàng / hẹn ngày / không có thêm — trang tính trước phần tách khi lên YCMH
            # (cùng luật allocation_utils.split_buy_qty).
            "available_qty": quote_line.available_qty,
            "backorder_date": _date_text(quote_line.backorder_date),
            "no_more": quote_line.no_more,
            # Giá dùng lại từ báo giá trước (còn hiệu lực) — ghi phiếu gốc để sale biết nguồn.
            "inherited_from": _inherited_doc(quote_line.inherited_from_id),
            # NCC chưa báo mà có giá lần trước (≤ 7 ngày): chỉ để hiện "chờ xác nhận", KHÔNG phải giá.
            "reference_price": _price_incl(recent_vendor_price(quote_line))
            if quote_line.quote_id.state == "sent" and not quote_line.price_unit else 0,
        }
    live = line._hlv_live_request_lines()
    requests = line.request_line_ids.sudo().request_id
    shortage = line._hlv_shortage()
    return {
        "id": line.id,
        "product_id": line.product_id.id,
        "locked": line.locked,
        "ordered_qty": sum(live.mapped("purchased_qty")),
        "request_names": live.request_id.mapped("name"),
        # Có YCMH bị từ chối mà chưa lên lại: chờ lên YCMH mới.
        "request_rejected": not live and any(r.state == "rejected" for r in requests),
        "rejected_names": requests.filtered(lambda r: r.state == "rejected").mapped("name"),
        # Có NCC đã chọn sẽ lên YCMH khi bấm nút (bảng tóm tắt xác nhận trước khi tạo).
        "to_request": any(o["to_request"] for o in offers.values()),
        "name": line.name or line.product_id.display_name,
        "qty": line.product_qty,
        # Chia SL: cần mua, đã chia cho các NCC, còn thiếu.
        "need_qty": line.need_qty,
        "chosen_qty": line._hlv_chosen_total(),
        "shortage": shortage,
        "uom": line.product_uom_id.name or "",
        "offers": offers,
        # Còn thiếu mà không NCC nào khác (chưa chọn) có giá để chọn thêm — hộp "Hỏi thêm NCC" tích sẵn.
        "needs_vendor": not line.locked and shortage > 0 and not any(
            o["price_unit"] and not o["unavailable"] and not o["selected"] for o in offers.values()
        ),
    }


def _inherited_doc(source_line):
    if not source_line:
        return ""
    source = source_line.sudo()
    return source.inquiry_line_id.inquiry_id.name or source.quote_id.name


def _request_payload(request):
    """YCMH kèm trạng thái (key để tô màu, nhãn để hiện); id để mở hộp xem YCMH (purchase_request_detail)."""
    return {
        "id": request.id,
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


def add_products_result(result):
    """Kết quả "Thêm sản phẩm" để báo sale (vendor_inquiry.action_add_products): món mới, món cộng dồn (SL trước →
    sau, NCC đang thu hồi món đó — sale biết món chưa được hỏi lại)."""
    return {
        "added": [line.name or line.product_id.display_name for line in result["added"]],
        "merged": [{
            "name": line.name or line.product_id.display_name,
            "before": before,
            "after": line.product_qty,
            "uom": line.product_uom_id.name or "",
            "withdrawn": line.quote_line_ids.filtered(
                lambda l: l.withdrawn and l.quote_id.state in ("sent", "quoted")
            ).quote_id.partner_id.commercial_partner_id.mapped("display_name"),
        } for line, before in result["merged"]],
    }


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
        requester=quotes.env["hlv.vendor.sale.contact"]._requester(first.inquiry_id.sale_code),
        password=access._shown_password() if access else "",
    )


def quote_share_result(quote):
    """Một NCC vừa được gửi phiếu (tạo phiếu / hỏi thêm NCC): tên, số báo giá, tin nhắn Zalo."""
    return {
        "vendor_name": quote.partner_id.commercial_partner_id.display_name,
        "name": quote.name,
        # Đủ giá còn hiệu lực từ báo giá trước — không cần gửi link cho NCC này.
        "reused": quote.state == "quoted",
        "share_message": share_message(quote),
    }


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
        "is_kit": bool(kit_bom(product)),
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
        # Combo (BoM kit): trang tách thành các mặt hàng con trước khi đưa vào phiếu (expand_lines).
        "is_kit": bool(kit_bom(product)),
    }


def crm_product_payload(crm):
    """Một hàng trên MISA CRM (kết quả misa.api.utils.crm_product_candidates) cho trang sale."""
    return {
        "code": (crm.get("code") or "").strip(),
        "name": crm.get("name") or "",
        "unit": crm.get("unit") or "",
        "price": crm.get("price") or 0,
        "tax": crm.get("tax") or "",
        # Combo: tạo được (dựng combo + BoM từ CRM — services/combo_lines.py) rồi tách thành mặt hàng con.
        "is_combo": bool(crm.get("is_combo")),
        "odoo_exists": bool(crm.get("odoo_exists")),
    }


def product_picks_payload(picks, names):
    """Gợi ý theo từng mặt hàng cho hộp lập phiếu: {product_id: {cheapest, delivered, recent, vendor_ids, evidence}}.
    Mỗi tiêu chí là {id, name} (rẻ nhất kèm giá, đã giao kèm count, gần nhất kèm date) hoặc None."""
    def vendor(partner_id, **extra):
        return dict({"id": partner_id, "name": names.get(partner_id, "")}, **extra) if partner_id else None

    def cheapest(pick):
        row = next((e for e in pick["evidence"] if e["partner_id"] == pick["cheapest"]), None)
        return vendor(pick["cheapest"], price=row["price"], price_incl=row["price_incl"]) if row else None

    return {
        product_id: {
            "cheapest": cheapest(pick),
            "delivered": vendor(pick["delivered"], count=pick["delivered_count"]),
            "recent": vendor(pick["recent"], date=_date_text(pick["recent_date"])),
            "vendor_ids": sorted(pick["vendors"]),
            # Dẫn chứng (nút "i"): giá mua lần gần nhất + hạng, đơn mua gần nhất, số lần giao được.
            "evidence": [{
                "id": item["partner_id"],
                "name": names.get(item["partner_id"], ""),
                "price": item["price"],
                "price_incl": item["price_incl"],
                "price_rank": item["price_rank"],
                "priced_count": item["priced_count"],
                "last_order": item["last_order"],
                "last_date": _date_text(item["last_date"]),
                "received_count": item["received_count"],
                "last_received": _date_text(item["last_received"]),
            } for item in pick["evidence"]],
        }
        for product_id, pick in picks.items()
    }


def suggestion_payload(item, products):
    matched = products.filtered(lambda p: p.id in item["product_ids"])
    return {
        "partner_id": item["partner_id"],
        # Mặt hàng NCC từng bán / có bảng giá — hộp lập phiếu tick sẵn đúng các mặt hàng này cho NCC.
        "product_ids": sorted(item["product_ids"]),
        "matched": len(item["product_ids"]),
        "total": len(products),
        "matched_products": ", ".join(matched.mapped("display_name")),
        "order_count": item["order_count"],
        "last_date": _date_text(item["last_date"]),
        "from_pricelist": item["from_pricelist"],
    }
