# -*- coding: utf-8 -*-
"""Trang tra giá: mọi giá của một sản phẩm theo từng NCC — giá ĐÃ MUA (đơn mua đã xác nhận)
và giá NCC TỪNG BÁO (báo giá NCC), của mọi mã sale.

Cố ý cho sale xem giá mua (trước đây gợi ý NCC giấu giá mua với sale): sale cần biết đã mua
bao nhiêu để báo khách / ép giá NCC. Đọc bằng sudo — sale không có quyền đơn mua.
"""

from ..models.vendor_quote_line import VAT_SELECTION
from ..models.vendor_quote_utils import local_date_text, summarize_vendor_prices
from .price_reuse import reuse_block_reason
from .vendor_chat import display_time

ROW_LIMIT = 200
VAT_LABELS = dict(VAT_SELECTION)


def _purchase_rows(env, product):
    lines = env["purchase.order.line"].sudo().search([
        ("product_id", "=", product.id),
        ("display_type", "=", False),
        ("order_id.state", "in", ("purchase", "done")),
    ], order="id desc", limit=ROW_LIMIT)
    rows = []
    for line in lines:
        order = line.order_id
        vendor = order.partner_id.commercial_partner_id
        day = order.date_approve or order.date_order
        # Giá thực mua sau chiết khấu dòng (nếu có) — "price" là SAU VAT (giá bên mình đọc và so),
        # "price_untaxed" chưa VAT ghi phụ.
        net = line.price_subtotal / line.product_qty if line.product_qty else line.price_unit
        gross = line.price_total / line.product_qty if line.product_qty else line.price_unit
        rows.append({
            "vendor_id": vendor.id,
            "vendor": vendor.display_name,
            "day": local_date_text(day, "%Y-%m-%d"),
            "date": local_date_text(day),
            "order": order.name,
            "qty": line.product_qty,
            "qty_received": line.qty_received,
            "uom": line.product_uom.name or "",
            "price_unit": line.price_unit,
            "discount": line.discount,
            "price": gross,
            "price_untaxed": net,
            "currency": order.currency_id.name or "",
            "invoice_name": line.hlv_invoice_name or "",
        })
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
        "vendors": summarize_vendor_prices(purchases, quotes),
        "purchases": purchases,
        "quotes": quotes,
    }
