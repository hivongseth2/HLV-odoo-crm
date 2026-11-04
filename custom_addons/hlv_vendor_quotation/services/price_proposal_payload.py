# -*- coding: utf-8 -*-
"""Dữ liệu JSON khối "Thu mua đề xuất giá" trong ngăn phiếu của trang /hoi-gia-ncc (models/po_price_proposal.py).

Đọc bằng sudo: sale không có quyền đơn mua / đề xuất giá — nơi gọi đã kiểm phiếu thuộc phạm vi mã sale.
"""

from ..models.po_price_proposal import KEEP_FROM, PROPOSAL_STATES, REQUOTE_FROM, SALE_TODO_STATES
from ..models.vendor_quote_utils import DATETIME_FMT, local_date_text

STATE_LABELS = dict(PROPOSAL_STATES)
# Đề xuất đã xong vẫn hiện vài cái gần nhất để sale biết kết quả; đã huỷ thì thôi.
PROPOSAL_LIMIT = 10


def inquiry_price_proposals(inquiry):
    """Đề xuất giá của các đơn mua lên từ phiếu (mới trước, bỏ cái thu mua đã huỷ)."""
    proposals = inquiry.env["hlv.po.price.proposal"].sudo().search(
        [("inquiry_id", "=", inquiry.id), ("state", "!=", "cancel")], order="id desc", limit=PROPOSAL_LIMIT)
    return [_proposal(p) for p in proposals]


def sale_todo_count(inquiry):
    """Số đề xuất giá của phiếu đang chờ sale làm (hỏi lại NCC / gửi thu mua duyệt)."""
    return inquiry.env["hlv.po.price.proposal"].sudo().search_count(
        [("inquiry_id", "=", inquiry.id), ("state", "in", SALE_TODO_STATES)])


def _other_offers(proposal):
    """Giá các NCC KHÁC đã báo cho cùng món trên phiếu (rẻ trước) — phiếu hỏi nhiều NCC thì sale thấy ngay khi hỏi lại
    NCC của đơn. Chỉ để tham khảo: đề xuất đổi giá trên đơn mua của NCC của đơn, không đổi NCC."""
    own = proposal.quote_line_id
    lines = own.inquiry_line_id.quote_line_ids.filtered(
        lambda l: l.quote_id != own.quote_id and l.quote_state in ("quoted", "done") and l.price_unit
        and not l.unavailable and not l.withdrawn)
    offers = [{"vendor": l.partner_id.commercial_partner_id.display_name, "price": l.price_unit * (1 + l.tax_rate / 100.0),
               "supply": l._availability_text()} for l in lines]
    return sorted(offers, key=lambda o: o["price"])


def _product(product):
    """{id, name} của sản phẩm cho form trên trang; không có → None."""
    return {"id": product.id, "name": product.display_name} if product else None


def _proposal(proposal):
    product = proposal.product_id.display_name or ""
    return {
        "id": proposal.id,
        "product": product,
        "product_id": proposal.product_id.id,
        "order": proposal.purchase_order_id.name,
        "order_id": proposal.purchase_order_id.id,
        # Ô giá trên bảng so giá (offer.line_id) — tô màu + nút thao tác ngay trên ô; đổi mã thì cả ô của mã mới.
        "quote_line_id": proposal.quote_line_id.id,
        "new_quote_line_id": proposal.new_quote_line_id.id,
        "vendor": proposal.partner_id.commercial_partner_id.display_name,
        "state": proposal.state,
        "state_label": "NCC gửi lại — giữ nguyên giá" if proposal.state == "quoted" and proposal.vendor_kept_price
        else STATE_LABELS.get(proposal.state, ""),
        "buyer": proposal.buyer_id.name or "",
        "buyer_note": proposal.buyer_note or "",
        "date": local_date_text(proposal.create_date, DATETIME_FMT),
        # Giá sau VAT là số chính (bên mình đọc và chốt theo giá sau VAT).
        "old_price": proposal.old_price_incl,
        "suggested_price": proposal.suggested_price_incl,
        "vendor_price": proposal.vendor_price_incl,
        "vendor_date": local_date_text(proposal.vendor_date, DATETIME_FMT),
        "tax_rate": proposal.tax_rate,
        "vendor_tax_rate": proposal.vendor_tax_rate,
        "new_price": proposal.new_price_incl,
        "vat_warning": proposal.vat_warning or "",
        "vendor_message": proposal.vendor_message or "",
        "reject_reason": proposal.reject_reason or "",
        "sale_note": proposal.sale_note or "",
        # SL / mã: trên đơn → thu mua đề xuất → sale chốt (form gửi điền sẵn cái sale chốt, chưa có thì của thu mua).
        "uom": proposal.uom_id.name or "",
        "old_qty": proposal.old_qty,
        "suggested_qty": proposal.suggested_qty,
        "suggested_product": _product(proposal.suggested_product_id),
        "new_qty": proposal.new_qty,
        "new_product": _product(proposal.new_product_id),
        "form_qty": proposal.new_qty or proposal.suggested_qty or proposal.old_qty,
        "form_product": _product(proposal.new_product_id or proposal.suggested_product_id or proposal.product_id),
        "change_text": proposal._change_text() if proposal._has_line_change() else "",
        "needs_vendor": proposal.needs_vendor,
        "qty_received": proposal.order_line_id.sudo().qty_received,
        "can_requote": proposal.state in REQUOTE_FROM and bool(proposal.quote_line_id),
        "vendor_kept_price": proposal.vendor_kept_price,
        # NCC giữ nguyên giá thì không có gì để thu mua duyệt (_sale_submit cũng chặn).
        "can_submit": proposal.state == "quoted" and bool(proposal.vendor_price_incl) and not proposal.vendor_kept_price,
        # NCC đã báo giá mới thì việc là gửi duyệt hoặc hỏi lại — "NCC giữ giá" chỉ còn khi NCC chưa báo / giữ nguyên.
        "can_keep": proposal.state in KEEP_FROM and not (proposal.vendor_price_incl and not proposal.vendor_kept_price),
        "other_offers": _other_offers(proposal),
    }
