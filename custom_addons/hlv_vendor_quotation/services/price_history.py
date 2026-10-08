# -*- coding: utf-8 -*-
"""Giá NCC đã báo cho một sản phẩm, của MỌI mã sale — để sale biết sản phẩm đã có người hỏi
giá (giá bao nhiêu, NCC nào, khi nào) và khỏi hỏi trùng.

Cố ý vượt phạm vi mã sale của trang: chỉ đưa giá / NCC / số phiếu / mã sale, không mở được
phiếu của sale khác (API phiếu vẫn kiểm mã sale). Đọc bằng sudo.
"""

from ..models.vendor_inquiry import CLOSE_REASONS
from ..models.vendor_quote_utils import local_date_text
from .price_reuse import reuse_block_reason
from .vendor_chat import display_time

QUOTED_STATES = ("quoted", "done")
SCAN_LIMIT = 300        # số dòng báo giá mới nhất đem ra lọc
PER_PRODUCT = 5         # tối đa giá mỗi sản phẩm
MAX_PRODUCTS = 12       # tối đa sản phẩm trong kết quả tìm


def _origin_status(line):
    """Vì sao giá trống để dùng lại (chỉ gọi khi dùng lại được): sale trước bỏ, hay đã mua NCC khác."""
    inquiry = line.inquiry_line_id.inquiry_id
    if inquiry.state == "closed":
        reason = dict(CLOSE_REASONS).get(inquiry.close_reason, "")
        return "sale trước đã bỏ" + (f" — {reason.lower()}" if reason and inquiry.close_reason != "auto" else "")
    return "sale trước đã mua NCC khác"


def _line_payload(line, today):
    reuse_note = reuse_block_reason(line, today)
    quote = line.quote_id
    inquiry = line.inquiry_line_id.inquiry_id
    vendor = quote.partner_id.commercial_partner_id
    return {
        "vendor": vendor.display_name,
        "vendor_id": vendor.id,
        "valid_until": local_date_text(quote.price_valid_until),
        "valid": bool(quote.price_valid_until) and quote.price_valid_until >= today,
        # Dùng lại được (lập phiếu mới là tự điền giá) — cùng luật với services/price_reuse.py.
        "reuse_note": reuse_note,
        "reusable": not reuse_note,
        # Giá chỉ đúng cho tối đa số lượng đã hỏi, đúng ĐVT đã hỏi.
        "qty": line.product_qty,
        "uom_id": line.product_uom_id.id,
        "uom": line.product_uom_id.name or "",
        "origin_status": _origin_status(line) if not reuse_note else "",
        "price_unit": line.price_unit,
        "price_incl": line.price_unit * (1 + line.tax_rate / 100.0),
        "vat": dict(line._fields["vat"].selection).get(line.vat, ""),
        "delivery_days": line.delivery_days,
        "date": display_time(quote.submit_date),
        "doc": inquiry.name or quote.name,
        "sale_code": inquiry.sale_code or "",
        "chosen": line.selected,
    }


def quoted_prices(env, product_ids=None, search=""):
    """[{product_id, product, prices: [..mới nhất trước]}] — theo product_ids, hoặc theo chữ
    tìm (mã / tên sản phẩm). Chỉ giá thật: NCC đã gửi, có đơn giá, không báo hết hàng.
    Không có điều kiện nào → []."""
    if not product_ids and not search:
        return []
    domain = [
        ("quote_id.state", "in", QUOTED_STATES),
        ("price_unit", ">", 0),
        ("unavailable", "=", False),
        ("product_id", "!=", False),
        # Bản kế thừa chỉ là bản sao giá gốc — hiện giá gốc thôi.
        ("inherited_from_id", "=", False),
    ]
    if product_ids:
        domain.append(("product_id", "in", list(product_ids)))
    if search:
        domain += ["|", ("product_id.default_code", "ilike", search), ("product_id.name", "ilike", search)]
    lines = env["hlv.vendor.quote.line"].sudo().search(domain, order="id desc", limit=SCAN_LIMIT)
    lines = lines.sorted(lambda l: l.quote_id.submit_date or l.create_date, reverse=True)
    today = env["hlv.vendor.quote"]._vendor_today()
    groups = {}
    for line in lines:
        group = groups.setdefault(line.product_id.id, {
            "product_id": line.product_id.id,
            "product": line.product_id.display_name,
            "name": line.product_id.display_name,
            "uom_id": line.product_uom_id.id,
            "uom": line.product_uom_id.name or "",
            "prices": [],
        })
        if len(group["prices"]) < PER_PRODUCT:
            group["prices"].append(_line_payload(line, today))
    return list(groups.values())[:MAX_PRODUCTS]
