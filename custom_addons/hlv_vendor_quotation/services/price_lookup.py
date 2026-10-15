# -*- coding: utf-8 -*-
"""Trang tra giá: mọi giá của một sản phẩm theo từng NCC — giá ĐÃ MUA (đơn mua đã xác nhận)
và giá NCC TỪNG BÁO (báo giá NCC), của mọi mã sale.

Cố ý cho sale xem giá mua (trước đây gợi ý NCC giấu giá mua với sale): sale cần biết đã mua
bao nhiêu để báo khách / ép giá NCC. Đọc bằng sudo — sale không có quyền đơn mua.
"""

from ..models.vendor_quote_line import VAT_SELECTION
from ..models.vendor_quote_utils import local_date_text, return_state, summarize_vendor_prices
from .price_reuse import reuse_block_reason
from .vendor_chat import display_time

ROW_LIMIT = 200
VAT_LABELS = dict(VAT_SELECTION)


def _receipt_facts(line):
    """SL nhập / SL trả NCC / ngày nhập đầu / ngày trả gần nhất của một dòng mua, ĐVT của dòng.

    Đếm thẳng từ phiếu kho đã xong, không dùng qty_received: phiếu trả bỏ tick "Update
    quantities on SO/PO" thì Odoo không trừ, sale sẽ thấy hàng còn dù đã trả NCC. Chỉ lấy chặng
    chạm kho NCC — chặng nội bộ của nhập nhiều bước không bị đếm trùng.
    """
    qty_in = qty_returned = 0.0
    received_at, returned_at = [], []
    for move in line.move_ids:
        if move.state != "done" or move.product_id != line.product_id:
            continue
        # Phiếu trả dùng ĐVT gốc của sản phẩm, có thể khác ĐVT trên đơn.
        qty = move.product_uom._compute_quantity(move.quantity, line.product_uom, rounding_method="HALF-UP")
        if move.location_dest_id.usage == "supplier":
            qty_returned += qty
            returned_at.append(move.date)
        elif move.location_id.usage == "supplier":
            qty_in += qty
            received_at.append(move.date)
    return {
        "qty_in": qty_in,
        "qty_returned": qty_returned,
        "received": local_date_text(min(received_at, default=None)),
        # yyyy-mm-dd để trang tính số ngày từ lúc đặt tới lúc hàng về.
        "received_day": local_date_text(min(received_at, default=None), "%Y-%m-%d"),
        "returned": local_date_text(max(returned_at, default=None)),
        "return_state": return_state(qty_in, qty_returned),
    }


def _purchase_rows(env, product):
    # Chỉ lần mua đã thực nhập kho: giá trên đơn chưa nhập chưa chắc là giá chốt. Lần nhập rồi
    # trả hết vẫn lấy — hiện mờ để sale biết lần mua đó đã bị trả.
    lines = env["purchase.order.line"].sudo().search([
        ("product_id", "=", product.id),
        ("display_type", "=", False),
        ("order_id.state", "in", ("purchase", "done")),
        ("move_ids", "any", [("state", "=", "done"), ("location_id.usage", "=", "supplier")]),
    ], order="id desc", limit=ROW_LIMIT)
    rows = []
    for line in lines:
        order = line.order_id
        vendor = order.partner_id.commercial_partner_id
        # Giá thực mua sau chiết khấu dòng (nếu có) — "price" là SAU VAT (giá bên mình đọc và so),
        # "price_untaxed" chưa VAT ghi phụ.
        net = line.price_subtotal / line.product_qty if line.product_qty else line.price_unit
        gross = line.price_total / line.product_qty if line.product_qty else line.price_unit
        rows.append({
            **_receipt_facts(line),
            "vendor_id": vendor.id,
            "vendor": vendor.display_name,
            "day": local_date_text(order.date_order, "%Y-%m-%d"),
            "date": local_date_text(order.date_order),
            "order": order.name,
            "qty": line.product_qty,
            "uom": line.product_uom.name or "",
            "price_unit": line.price_unit,
            "discount": line.discount,
            "price": gross,
            "price_untaxed": net,
            "currency": order.currency_id.name or "",
            "invoice_name": line.hlv_invoice_name or "",
        })
    # Tìm theo id để lấy đúng 200 dòng mới tạo; hiện theo ngày đơn hàng (đơn nhập bù có thể mang ngày cũ).
    rows.sort(key=lambda row: row["day"], reverse=True)
    return rows


def _quote_rows(env, product):
    QuoteLine = env["hlv.vendor.quote.line"].sudo()
    today = env["hlv.vendor.quote"]._vendor_today()
    lines = QuoteLine.search([
        ("product_id", "=", product.id),
        ("quote_id.state", "in", ("quoted", "done")),
        # Bản kế thừa chỉ là bản sao — hiện giá gốc NCC báo.
        ("inherited_from_id", "=", False),
        "|", ("price_unit", ">", 0), ("unavailable", "=", True),
    ], order="id desc", limit=ROW_LIMIT)
    rows = []
    for line in lines:
        quote = line.quote_id
        inquiry = line.inquiry_line_id.inquiry_id
        vendor = quote.partner_id.commercial_partner_id
        note = reuse_block_reason(line, today)
        rows.append({
            "vendor_id": vendor.id,
            "vendor": vendor.display_name,
            "day": local_date_text(quote.submit_date, "%Y-%m-%d"),
            "date": display_time(quote.submit_date),
            "doc": inquiry.name or quote.name,
            "sale_code": inquiry.sale_code or "",
            "qty": line.product_qty,
            "uom": line.product_uom_id.name or "",
            # Giá đem so / hiện chính: sau VAT (summarize_vendor_prices lấy min theo "price").
            "price": line.price_unit * (1 + line.tax_rate / 100.0),
            "price_untaxed": line.price_unit,
            "vat": VAT_LABELS.get(line.vat, ""),
            "delivery_days": line.delivery_days,
            "unavailable": line.unavailable,
            "chosen": line.selected,
            "valid_until": local_date_text(quote.price_valid_until),
            "reusable": not note,
            "reuse_note": note,
        })
    return rows


def product_prices(env, product):
    """{product, vendors (tóm tắt theo NCC), purchases, quotes} — mới nhất trước."""
    purchases = _purchase_rows(env, product)
    quotes = _quote_rows(env, product)
    uom = product.uom_po_id or product.uom_id
    return {
        "product": {
            "id": product.id,
            "name": product.display_name,
            "code": product.default_code or "",
            "uom_id": uom.id,
            "uom": uom.name or "",
        },
        # Lần mua đã trả hết không còn là giá mua thật — không cho làm "gần nhất" / "thấp nhất".
        "vendors": summarize_vendor_prices([r for r in purchases if r["return_state"] != "full"], quotes),
        "purchases": purchases,
        "quotes": quotes,
    }
