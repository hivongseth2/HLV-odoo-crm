# -*- coding: utf-8 -*-
"""Dữ liệu JSON khối "Thu mua đề xuất giá" trong ngăn phiếu của trang /hoi-gia-ncc (models/po_price_proposal.py).

Đọc bằng sudo: sale không có quyền đơn mua / đề xuất giá — nơi gọi đã kiểm phiếu thuộc phạm vi mã sale.
"""

from ..models.po_price_proposal import KEEP_FROM, PROPOSAL_STATES, REQUOTE_FROM
from ..models.price_proposal_utils import requote_message
from ..models.vendor_quote_utils import DATETIME_FMT, local_date_text

STATE_LABELS = dict(PROPOSAL_STATES)
# Đề xuất đã xong vẫn hiện vài cái gần nhất để sale biết kết quả; đã huỷ thì thôi.
PROPOSAL_LIMIT = 10


def inquiry_price_proposals(inquiry):
    """Đề xuất giá của các đơn mua lên từ phiếu (mới trước, bỏ cái thu mua đã huỷ)."""
    proposals = inquiry.env["hlv.po.price.proposal"].sudo().search(
        [("inquiry_id", "=", inquiry.id), ("state", "!=", "cancel")], order="id desc", limit=PROPOSAL_LIMIT)
    return [_proposal(p) for p in proposals]


def _proposal(proposal):
    product = proposal.product_id.display_name or ""
    return {
        "id": proposal.id,
        "product": product,
        "order": proposal.purchase_order_id.name,
        "order_id": proposal.purchase_order_id.id,
        "vendor": proposal.partner_id.commercial_partner_id.display_name,
        "state": proposal.state,
        "state_label": STATE_LABELS.get(proposal.state, ""),
        "buyer": proposal.buyer_id.name or "",
        "buyer_note": proposal.buyer_note or "",
        "date": local_date_text(proposal.create_date, DATETIME_FMT),
        # Giá sau VAT là số chính (bên mình đọc và chốt theo giá sau VAT).
        "old_price": proposal.old_price_incl,
        "suggested_price": proposal.suggested_price_incl,
        "vendor_price": proposal.vendor_price_incl,
        "new_price": proposal.new_price_incl,
        "vat_warning": proposal.vat_warning or "",
        "vendor_message": proposal.vendor_message or "",
        "reject_reason": proposal.reject_reason or "",
        "sale_note": proposal.sale_note or "",
        "default_message": requote_message(product, proposal.suggested_price_incl),
        "can_requote": proposal.state in REQUOTE_FROM and bool(proposal.quote_line_id),
        "can_submit": proposal.state == "quoted",
        "can_keep": proposal.state in KEEP_FROM,
    }
