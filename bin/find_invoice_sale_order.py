# -*- coding: utf-8 -*-
"""
Read-only lookup: find the Odoo sale order behind a MISA/meInvoice invoice.

Odoo.sh:
    odoo-bin shell -d "$PGDATABASE" --no-http < bin/find_invoice_sale_order.py

Optional overrides:
    INVOICE_NO=00005928 INVOICE_SERIES=1C26MLV \
    INVOICE_CODE=M1-26-WJ1VA-00000005966 \
    odoo-bin shell -d "$PGDATABASE" --no-http < bin/find_invoice_sale_order.py
"""

import json
import os


INVOICE_NO = (os.environ.get("INVOICE_NO") or "00005928").strip()
INVOICE_SERIES = (os.environ.get("INVOICE_SERIES") or "1C26MLV").strip()
INVOICE_CODE = (
    os.environ.get("INVOICE_CODE") or "M1-26-WJ1VA-00000005966"
).strip()
INVOICE_DATE = (os.environ.get("INVOICE_DATE") or "2026-07-16").strip()
SKU = (os.environ.get("SKU") or "48-22-8902").strip()
TOTAL = float(os.environ.get("TOTAL") or "144061")
AMOUNT_TOLERANCE = float(os.environ.get("AMOUNT_TOLERANCE") or "1")


def model_exists(model_name):
    return model_name in env.registry.models  # noqa: F821


def empty(model_name):
    return env[model_name].browse()  # noqa: F821


def add_reason(reason_map, records, reason):
    for record in records:
        reason_map.setdefault(record.id, []).append(reason)


def text_snippet(value, needle, width=180):
    text = " ".join((value or "").split())
    if not text:
        return ""
    pos = text.casefold().find((needle or "").casefold())
    if pos < 0:
        return text[:width]
    start = max(pos - width // 2, 0)
    return text[start : start + width]


def iter_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_dicts(child)


def parsed_json(value):
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return {}
    try:
        return json.loads(value)
    except Exception:
        return {}


def sale_url(order):
    return "%s/web#id=%s&model=sale.order&view_type=form" % (base_url, order.id)


def print_order(order, reasons):
    print(
        "  SO id=%s | name=%s | Shopee=%s | state=%s | total=%s | customer=%s"
        % (
            order.id,
            order.name or "",
            getattr(order, "shopee_order_ref", "") or "",
            order.state or "",
            order.amount_total,
            order.partner_id.display_name or "",
        )
    )
    print("    reason: %s" % "; ".join(sorted(set(reasons))))
    print("    url   : %s" % sale_url(order))


number_variants = {INVOICE_NO}
if INVOICE_NO.isdigit():
    number_variants.add(str(int(INVOICE_NO)))
number_variants.discard("")
number_variants = sorted(number_variants)

base_url = (
    env["ir.config_parameter"].sudo().get_param("web.base.url")  # noqa: F821
    or ""
).rstrip("/")

SaleOrder = env["sale.order"].sudo()  # noqa: F821
orders = empty("sale.order")
order_reasons = {}
exact_order_ids = set()

print("=" * 100)
print("TRA DON HANG CUA HOA DON MISA / meInvoice (READ-ONLY)")
print("=" * 100)
print("So hoa don : %s (variants: %s)" % (INVOICE_NO, ", ".join(number_variants)))
print("Ky hieu    : %s" % INVOICE_SERIES)
print("Ma CQT     : %s" % INVOICE_CODE)
print("Ngay HD    : %s" % INVOICE_DATE)
print("SKU / Tong: %s / %s" % (SKU, TOTAL))

# 1) meInvoice stores a direct, required Many2one to sale.order.
invoice_records = None
if model_exists("meinvoice.invoice"):
    Invoice = env["meinvoice.invoice"].sudo()  # noqa: F821
    invoice_records = empty("meinvoice.invoice")
    invoice_reasons = {}

    if "inv_no" in Invoice._fields:
        found = Invoice.search([("inv_no", "in", number_variants)])
        invoice_records |= found
        add_reason(invoice_reasons, found, "inv_no exact")
    if INVOICE_CODE and "inv_code" in Invoice._fields:
        found = Invoice.search([("inv_code", "=", INVOICE_CODE)])
        invoice_records |= found
        add_reason(invoice_reasons, found, "inv_code/Ma CQT exact")

    print("\n[1] meInvoice invoice khop chinh xac: %s" % len(invoice_records))
    for inv in invoice_records.sorted(key=lambda rec: rec.id):
        inv_series = (
            getattr(inv, "inv_series_result", False)
            or getattr(inv, "inv_series", False)
            or ""
        )
        print(
            "  Invoice id=%s | series=%s | no=%s | code=%s | state=%s | SO=%s"
            % (
                inv.id,
                inv_series,
                getattr(inv, "inv_no", "") or "",
                getattr(inv, "inv_code", "") or "",
                getattr(inv, "state", "") or "",
                inv.sale_order_id.name if inv.sale_order_id else "(missing)",
            )
        )
        print("    reason: %s" % "; ".join(invoice_reasons.get(inv.id, [])))
        if inv.sale_order_id:
            orders |= inv.sale_order_id
            exact_order_ids.add(inv.sale_order_id.id)
            add_reason(
                order_reasons,
                inv.sale_order_id,
                "meinvoice.invoice id=%s lien ket truc tiep" % inv.id,
            )
else:
    print("\n[1] Model meinvoice.invoice khong ton tai tren database nay.")

# 2) Backward-compatible result fields are also persisted directly on sale.order.
direct_sale_fields = {
    "misa_meinvoice_inv_no": number_variants,
    "misa_meinvoice_inv_code": [INVOICE_CODE] if INVOICE_CODE else [],
}
print("\n[2] sale.order khop field ket qua meInvoice:")
direct_count = 0
for field_name, values in direct_sale_fields.items():
    if field_name not in SaleOrder._fields or not values:
        continue
    found = SaleOrder.search([(field_name, "in", values)])
    if found:
        direct_count += len(found)
        orders |= found
        exact_order_ids.update(found.ids)
        add_reason(order_reasons, found, "%s exact" % field_name)
        for order in found:
            print("  %s=%s -> %s (id=%s)" % (
                field_name, getattr(order, field_name), order.name, order.id,
            ))
if not direct_count:
    print("  Khong co.")

# 3) Read AMIS callback logs. A matching callback org_refid maps back to fields on sale.order.
matched_logs = empty("amis.callback.log") if model_exists("amis.callback.log") else None
matched_lines = (
    empty("amis.callback.log.line") if model_exists("amis.callback.log.line") else None
)
log_reasons = {}
line_reasons = {}
callback_needles = [value for value in (INVOICE_CODE, INVOICE_NO) if value]

if matched_logs is not None:
    Log = env["amis.callback.log"].sudo()  # noqa: F821
    for needle in callback_needles:
        for field_name in ("raw_payload", "data_payload"):
            found = Log.search([(field_name, "ilike", needle)])
            matched_logs |= found
            add_reason(log_reasons, found, "%s contains %s" % (field_name, needle))

if matched_lines is not None:
    Line = env["amis.callback.log.line"].sudo()  # noqa: F821
    for needle in callback_needles:
        found = Line.search([("raw_json", "ilike", needle)])
        matched_lines |= found
        add_reason(line_reasons, found, "raw_json contains %s" % needle)
    if matched_logs:
        matched_lines |= matched_logs.mapped("detail_line_ids")

callback_refids = set()
callback_refnos = set()
callback_objects = []
if matched_logs:
    for log in matched_logs:
        callback_objects.append(parsed_json(log.data_payload))
if matched_lines:
    for line in matched_lines:
        if line.org_refid:
            callback_refids.add(line.org_refid.strip())
        callback_objects.append(parsed_json(line.raw_json))

for payload in callback_objects:
    for item in iter_dicts(payload):
        for key in ("org_refid", "refid", "misa_refid"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                callback_refids.add(value.strip())
        for key in ("org_refno",):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                callback_refnos.add(value.strip())

callback_orders = empty("sale.order")
for field_name in (
    "misa_sa_voucher_org_refid",
    "misa_sa_invoice_org_refid",
    "misa_meinvoice_ref_id",
    "misa_meinvoice_transaction_id",
):
    if callback_refids and field_name in SaleOrder._fields:
        found = SaleOrder.search([(field_name, "in", sorted(callback_refids))])
        callback_orders |= found
        add_reason(order_reasons, found, "callback org_refid -> %s" % field_name)
if callback_refnos:
    found = SaleOrder.search([("name", "in", sorted(callback_refnos))])
    callback_orders |= found
    add_reason(order_reasons, found, "callback org_refno -> sale.order.name")

orders |= callback_orders
exact_order_ids.update(callback_orders.ids)

print("\n[3] AMIS callback co chua so HD/Ma CQT:")
if not matched_logs and not matched_lines:
    print("  Khong tim thay callback nao chua dung chuoi can tra.")
else:
    print(
        "  Logs=%s | Lines=%s | RefIDs=%s | RefNos=%s"
        % (
            len(matched_logs or []),
            len(matched_lines or []),
            len(callback_refids),
            len(callback_refnos),
        )
    )
    for log in (matched_logs or empty("amis.callback.log")).sorted(
        key=lambda rec: rec.id, reverse=True
    )[:20]:
        reason = "; ".join(log_reasons.get(log.id, []))
        needle = next(
            (item for item in callback_needles if item.casefold() in (log.raw_payload or "").casefold()),
            callback_needles[0] if callback_needles else "",
        )
        print(
            "  Log id=%s | received=%s | data_type=%s | state=%s | %s"
            % (log.id, log.received_at, log.data_type, log.state, reason)
        )
        print("    %s" % text_snippet(log.raw_payload or log.data_payload, needle))

# 4) Evidence fallback from the visible invoice facts. This is intentionally marked as candidate only.
candidate_orders = empty("sale.order")
candidate_domain = [
    ("amount_total", ">=", TOTAL - AMOUNT_TOLERANCE),
    ("amount_total", "<=", TOTAL + AMOUNT_TOLERANCE),
]
if SKU:
    candidate_domain.append(("order_line.product_id.default_code", "=", SKU))
candidate_orders = SaleOrder.search(candidate_domain, order="date_order desc, id desc", limit=50)
orders |= candidate_orders
add_reason(
    order_reasons,
    candidate_orders,
    "UNG VIEN: amount_total=%s (+/-%s) va SKU=%s" % (
        TOTAL, AMOUNT_TOLERANCE, SKU,
    ),
)

print("\n[4] Ung vien theo tong tien + SKU (khong phai bang chung exact): %s" % len(candidate_orders))
for order in candidate_orders:
    print("  %s | id=%s | date=%s | total=%s | Shopee=%s" % (
        order.name,
        order.id,
        order.date_order,
        order.amount_total,
        getattr(order, "shopee_order_ref", "") or "",
    ))

print("\n" + "=" * 100)
exact_orders = SaleOrder.browse(sorted(exact_order_ids)).exists()
if len(exact_orders) == 1:
    print("KET LUAN EXACT: hoa don thuoc don hang:")
    print_order(exact_orders, order_reasons.get(exact_orders.id, []))
elif len(exact_orders) > 1:
    print("CO NHIEU KET QUA EXACT (%s), can doi chieu them:" % len(exact_orders))
    for order in exact_orders:
        print_order(order, order_reasons.get(order.id, []))
elif len(candidate_orders) == 1:
    print("KHONG CO LIEN KET EXACT. Chi co 1 UNG VIEN theo tong tien + SKU:")
    print_order(candidate_orders, order_reasons.get(candidate_orders.id, []))
else:
    print("KHONG XAC DINH DUOC 1 DON EXACT.")
    print("So ung vien theo tong tien + SKU: %s" % len(candidate_orders))
    for order in candidate_orders:
        print_order(order, order_reasons.get(order.id, []))

print("=" * 100)
print("Script chi doc du lieu, khong write/unlink/commit.")
