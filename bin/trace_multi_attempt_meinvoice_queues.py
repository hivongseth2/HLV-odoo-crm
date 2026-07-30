# -*- coding: utf-8 -*-
"""
Read-only audit of every meInvoice webhook queue processed more than once.

Odoo.sh:
    odoo-bin shell -d "$PGDATABASE" --no-http \
      < bin/trace_multi_attempt_meinvoice_queues.py
"""

import json
from collections import defaultdict
from datetime import timedelta

from odoo import fields


UTC_OFFSET_HOURS = 7
NEIGHBOR_RADIUS = 4


def local_dt(value):
    if not value:
        return ""
    return fields.Datetime.to_string(
        fields.Datetime.to_datetime(value) + timedelta(hours=UTC_OFFSET_HOURS)
    )


def local_date(value):
    text = local_dt(value)
    return text[:10] if text else ""


def invoice_ref_id(invoice):
    if not invoice or not invoice.invoice_data_json:
        return ""
    try:
        data = json.loads(invoice.invoice_data_json)
    except Exception:
        return ""
    return (data.get("RefID") or "").strip() if isinstance(data, dict) else ""


def order_url(order):
    return "%s/web#id=%s&model=sale.order&view_type=form" % (
        base_url,
        order.id,
    )


def numeric_invoice_no(value):
    text = (value or "").strip()
    return int(text) if text.isdigit() else None


base_url = (
    env["ir.config_parameter"].sudo().get_param("web.base.url")  # noqa: F821
    or ""
).rstrip("/")

Queue = env["amis.webhook.queue"].sudo()  # noqa: F821
Invoice = env["meinvoice.invoice"].sudo()  # noqa: F821
SaleOrder = env["sale.order"].sudo()  # noqa: F821

queues = Queue.search(
    [("attempts", ">", 1)],
    order="create_date, id",
)

print("=" * 140)
print("TRACE TAT CA meInvoice QUEUE CO attempts > 1 (READ-ONLY)")
print("=" * 140)
print("Tong queue: %s" % len(queues))
print(
    "Luu y: queue done da xoa error_msg cu; action_retry thu cong con reset attempts=0, "
    "nen day la so lieu toi thieu."
)

risk_groups = defaultdict(list)
orders_with_multi_attempt = SaleOrder.browse()

for queue in queues:
    order = queue.sale_order_id
    if not order and queue.order_ref:
        order = SaleOrder.search([("shopee_order_ref", "=", queue.order_ref)], limit=1)
    if order:
        orders_with_multi_attempt |= order

    linked_invoice = queue.meinvoice_invoice_id
    all_invoices = (
        Invoice.search([("sale_order_id", "=", order.id)], order="create_date, id")
        if order else Invoice.browse()
    )
    current_invoice = linked_invoice or all_invoices.filtered(
        lambda inv: inv.state not in ("draft", "cancelled")
    )[:1] or all_invoices[:1]

    inv_date = (
        current_invoice.inv_date_result or current_invoice.inv_date
        if current_invoice else False
    )
    queue_first_possible_date = local_date(queue.create_date)
    inv_date_text = str(inv_date or "")

    if queue.state == "done" and current_invoice:
        if queue_first_possible_date and inv_date_text and inv_date_text > queue_first_possible_date:
            risk = "HIGH_DUP_RISK"
        else:
            risk = "REVIEW_DONE_RETRY"
    elif queue.state in ("error", "processing"):
        risk = "STILL_FAILED"
    else:
        risk = "REVIEW"
    risk_groups[risk].append(queue)

    print("\n[%s] Q id=%s | attempts=%s | state=%s" % (
        risk,
        queue.id,
        queue.attempts,
        queue.state,
    ))
    print(
        "  create_local=%s | processed_local=%s | last_error=%s"
        % (
            local_dt(queue.create_date),
            local_dt(queue.processed_at),
            " ".join((queue.error_msg or "").split())[:300] or "(cleared)",
        )
    )
    print(
        "  SO=%s(id=%s) | Shopee=%s | total=%s | customer=%s"
        % (
            order.name if order else "(missing)",
            order.id if order else "",
            queue.order_ref or "",
            order.amount_total if order else "",
            order.partner_id.display_name if order else "",
        )
    )

    if current_invoice:
        print(
            "  CURRENT INV id=%s | state=%s | date=%s/%s | series=%s | "
            "no=%s | code=%s | transaction=%s"
            % (
                current_invoice.id,
                current_invoice.state,
                current_invoice.inv_date or "",
                current_invoice.inv_date_result or "",
                current_invoice.inv_series_result or current_invoice.inv_series or "",
                current_invoice.inv_no or "",
                current_invoice.inv_code or "",
                current_invoice.transaction_id or "",
            )
        )
        print(
            "  CURRENT RefID invoice_json=%s | sale_order=%s"
            % (
                invoice_ref_id(current_invoice),
                getattr(order, "misa_meinvoice_ref_id", "") if order else "",
            )
        )
    else:
        print("  CURRENT INV: NONE")

    if len(all_invoices) > 1:
        print("  ALL INVOICES FOR SO: %s" % len(all_invoices))
        for inv in all_invoices:
            print(
                "    id=%s state=%s create_local=%s date=%s/%s no=%s code=%s tx=%s"
                % (
                    inv.id,
                    inv.state,
                    local_dt(inv.create_date),
                    inv.inv_date or "",
                    inv.inv_date_result or "",
                    inv.inv_no or "",
                    inv.inv_code or "",
                    inv.transaction_id or "",
                )
            )

    if current_invoice:
        inv_number = numeric_invoice_no(current_invoice.inv_no)
        series = current_invoice.inv_series_result or current_invoice.inv_series or ""
        if inv_number is not None and series:
            low = max(inv_number - NEIGHBOR_RADIUS, 0)
            high = inv_number + NEIGHBOR_RADIUS
            number_texts = [
                str(number).zfill(len(current_invoice.inv_no))
                for number in range(low, high + 1)
            ]
            neighbors = Invoice.search([
                ("inv_no", "in", number_texts),
                "|",
                ("inv_series_result", "=", series),
                ("inv_series", "=", series),
            ])
            existing = {
                numeric_invoice_no(inv.inv_no)
                for inv in neighbors
                if numeric_invoice_no(inv.inv_no) is not None
            }
            missing = [
                str(number).zfill(len(current_invoice.inv_no))
                for number in range(low, high + 1)
                if number not in existing
            ]
            print(
                "  LOCAL SEQUENCE around %s: missing_in_odoo=%s"
                % (
                    current_invoice.inv_no,
                    ", ".join(missing) if missing else "(none)",
                )
            )

    if order:
        print("  %s" % order_url(order))

# Also report SOs that currently retain more than one durable invoice record.
multi_invoice_orders = []
for order in orders_with_multi_attempt:
    records = Invoice.search([("sale_order_id", "=", order.id)])
    published = records.filtered(lambda inv: inv.state not in ("draft", "cancelled"))
    if len(records) > 1 or len(published) > 1:
        multi_invoice_orders.append((order, records, published))

print("\n" + "=" * 140)
print("SUMMARY")
print("=" * 140)
for key in ("HIGH_DUP_RISK", "REVIEW_DONE_RETRY", "STILL_FAILED", "REVIEW"):
    print("%-20s : %s" % (key, len(risk_groups.get(key, []))))
    for queue in risk_groups.get(key, []):
        order = queue.sale_order_id
        print(
            "  Q%s attempts=%s | SO=%s | Shopee=%s | current_inv=%s"
            % (
                queue.id,
                queue.attempts,
                order.name if order else "(missing)",
                queue.order_ref or "",
                queue.meinvoice_invoice_id.inv_no or "(none)",
            )
        )

print("SO co >1 durable invoice record trong nhom retry: %s" % len(multi_invoice_orders))
for order, records, published in multi_invoice_orders:
    print(
        "  %s id=%s | records=%s | published=%s | %s"
        % (
            order.name,
            order.id,
            len(records),
            len(published),
            order_url(order),
        )
    )
print("=" * 140)
print("Script chi doc du lieu, khong write/unlink/commit.")
