# -*- coding: utf-8 -*-
"""
Read-only monthly meInvoice audit with the configured publish time window.

Odoo.sh:
    MONTH=2026-07 odoo-bin shell -d "$PGDATABASE" --no-http \
      < bin/audit_meinvoice_month.py

Optional:
    SHOW_ALL_QUEUES=0 MONTH=2026-07 odoo-bin shell -d "$PGDATABASE" --no-http \
      < bin/audit_meinvoice_month.py
"""

import os
from collections import defaultdict
from datetime import datetime, time, timedelta

from odoo import fields


MONTH = os.environ.get("MONTH") or "2026-06"
UTC_OFFSET_HOURS = int(os.environ.get("UTC_OFFSET_HOURS") or "7")
SHOW_ALL_QUEUES = (os.environ.get("SHOW_ALL_QUEUES") or "1").lower() not in (
    "0", "false", "no",
)
SHOW_ALL_INVOICES = (os.environ.get("SHOW_ALL_INVOICES") or "1").lower() not in (
    "0", "false", "no",
)
PREVIOUS_NUMBER_SCAN = int(os.environ.get("PREVIOUS_NUMBER_SCAN") or "5")


def parse_month(value):
    try:
        start = datetime.strptime(value, "%Y-%m").date().replace(day=1)
    except ValueError:
        raise SystemExit("MONTH phai co dang YYYY-MM, dang nhan: %s" % value)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def as_local(value):
    if not value:
        return None
    return fields.Datetime.to_datetime(value) + timedelta(hours=UTC_OFFSET_HOURS)


def local_text(value):
    local = as_local(value)
    return fields.Datetime.to_string(local) if local else ""


def float_time_text(value):
    hour = int(value)
    minute = int(round((float(value) - hour) * 60))
    return "%02d:%02d" % (hour, minute)


def inside_window(local_value, hour_from, hour_to, skip_sunday=True):
    if not local_value:
        return False
    if skip_sunday and local_value.isoweekday() == 7:
        return False
    current = local_value.hour + local_value.minute / 60.0 + local_value.second / 3600.0
    return hour_from <= current < hour_to


def invoice_number(value):
    text = (value or "").strip()
    return int(text) if text.isdigit() else None


def invoice_series(invoice):
    return (
        invoice.inv_series_result
        or invoice.inv_series
        or ""
    ).strip()


def invoice_date(invoice):
    return invoice.inv_date_result or invoice.inv_date


def order_url(order):
    return "%s/web#id=%s&model=sale.order&view_type=form" % (
        base_url,
        order.id,
    )


month_from, month_to = parse_month(MONTH)
local_from = datetime.combine(month_from, time.min)
local_to = datetime.combine(month_to, time.min)
utc_from = local_from - timedelta(hours=UTC_OFFSET_HOURS)
utc_to = local_to - timedelta(hours=UTC_OFFSET_HOURS)
utc_from_text = fields.Datetime.to_string(utc_from)
utc_to_text = fields.Datetime.to_string(utc_to)

Config = env["amis.callback.config"].sudo()  # noqa: F821
config = Config.search([], limit=1)
restricted = bool(config and config.webhook_publish_time_restrict)
hour_from = float(config.webhook_publish_time_from) if config else 7.0
hour_to = float(config.webhook_publish_time_to) if config else 16.5
deferred_action = (
    config.webhook_publish_deferred_action if config else ""
)

Queue = env["amis.webhook.queue"].sudo()  # noqa: F821
Invoice = env["meinvoice.invoice"].sudo()  # noqa: F821
SaleOrder = env["sale.order"].sudo()  # noqa: F821

base_url = (
    env["ir.config_parameter"].sudo().get_param("web.base.url")  # noqa: F821
    or ""
).rstrip("/")

queues = Queue.search([
    "|",
    "&",
    ("create_date", ">=", utc_from_text),
    ("create_date", "<", utc_to_text),
    "&",
    ("processed_at", ">=", utc_from_text),
    ("processed_at", "<", utc_to_text),
], order="create_date, id")

invoices = Invoice.browse()
for field_name in ("inv_date", "inv_date_result"):
    if field_name in Invoice._fields:
        invoices |= Invoice.search([
            (field_name, ">=", str(month_from)),
            (field_name, "<", str(month_to)),
        ])
invoices = invoices.sorted(
    key=lambda inv: (invoice_date(inv) or month_from, invoice_number(inv.inv_no) or 0, inv.id)
)

number_sets = defaultdict(set)
invoice_by_series_number = defaultdict(list)
for inv in invoices:
    number = invoice_number(inv.inv_no)
    series = invoice_series(inv)
    if number is None or not series:
        continue
    number_sets[series].add(number)
    invoice_by_series_number[(series, number)].append(inv)

# Use the full database for adjacency checks so a queue created at month-end and
# published next month is not falsely flagged merely because its neighbors fall
# outside the selected reporting month.
all_number_sets = defaultdict(set)
for inv in Invoice.search([("inv_no", "!=", False)]):
    number = invoice_number(inv.inv_no)
    series = invoice_series(inv)
    if number is not None and series:
        all_number_sets[series].add(number)


def immediately_missing_before(invoice):
    number = invoice_number(invoice.inv_no)
    series = invoice_series(invoice)
    if number is None or not series:
        return []
    existing = all_number_sets.get(series, set())
    missing = []
    for candidate in range(number - 1, max(number - PREVIOUS_NUMBER_SCAN - 1, -1), -1):
        if candidate in existing:
            break
        missing.append(candidate)
    return list(reversed(missing))


def queue_current_invoice(queue, order):
    if queue.meinvoice_invoice_id:
        return queue.meinvoice_invoice_id
    if not order:
        return Invoice.browse()
    return Invoice.search([
        ("sale_order_id", "=", order.id),
        ("state", "not in", ("draft", "cancelled")),
    ], order="create_date desc, id desc", limit=1)


print("=" * 150)
print("AUDIT meInvoice TOAN THANG %s (READ-ONLY)" % MONTH)
print("=" * 150)
print("Local month : %s 00:00:00 -> %s 00:00:00 (exclusive)" % (
    month_from,
    month_to,
))
print("UTC domain  : >= %s and < %s" % (utc_from_text, utc_to_text))
print(
    "Publish rule: restricted=%s | %s <= local time < %s | Sunday skipped | deferred_action=%s"
    % (
        restricted,
        float_time_text(hour_from),
        float_time_text(hour_to),
        deferred_action or "(empty)",
    )
)
print("Queues=%s | Invoices=%s" % (len(queues), len(invoices)))

if SHOW_ALL_INVOICES:
    print("\n[1] TAT CA HOA DON CO invoice date TRONG THANG: %s" % len(invoices))
    for inv in invoices:
        order = inv.sale_order_id
        print(
            "  INV id=%s | date=%s/%s | state=%s | series=%s | no=%s | "
            "code=%s | total=%s | SO=%s(id=%s) | Shopee=%s"
            % (
                inv.id,
                inv.inv_date or "",
                inv.inv_date_result or "",
                inv.state,
                invoice_series(inv),
                inv.inv_no or "",
                inv.inv_code or "",
                inv.total_amount_oc,
                order.name if order else "(missing)",
                order.id if order else "",
                getattr(order, "shopee_order_ref", "") if order else "",
            )
        )

gap_ranges_by_series = {}
print("\n[2] CAC KHOANG SO HOA DON THIEU TRONG ODOO")
for series, existing in sorted(number_sets.items()):
    if not existing:
        continue
    minimum = min(existing)
    maximum = max(existing)
    missing = [number for number in range(minimum, maximum + 1) if number not in existing]
    ranges = []
    if missing:
        range_start = previous = missing[0]
        for number in missing[1:]:
            if number == previous + 1:
                previous = number
                continue
            ranges.append((range_start, previous))
            range_start = previous = number
        ranges.append((range_start, previous))
    gap_ranges_by_series[series] = ranges
    print(
        "  series=%s | min=%s max=%s existing=%s missing=%s"
        % (
            series,
            str(minimum).zfill(8),
            str(maximum).zfill(8),
            len(existing),
            sum(end - start + 1 for start, end in ranges),
        )
    )
    if not ranges:
        print("    gaps=(none)")
    for start, end in ranges:
        label = (
            str(start).zfill(8)
            if start == end
            else "%s -> %s" % (str(start).zfill(8), str(end).zfill(8))
        )
        print("    gap=%s" % label)

risk_groups = defaultdict(list)
queue_rows = []
orders_seen = SaleOrder.browse()

for queue in queues:
    order = queue.sale_order_id
    if not order and queue.order_ref:
        order = SaleOrder.search([("shopee_order_ref", "=", queue.order_ref)], limit=1)
    if order:
        orders_seen |= order

    current_invoice = queue_current_invoice(queue, order)
    create_local = as_local(queue.create_date)
    processed_local = as_local(queue.processed_at)
    created_outside = restricted and not inside_window(
        create_local, hour_from, hour_to,
    )
    processed_outside = (
        restricted
        and bool(processed_local)
        and not inside_window(processed_local, hour_from, hour_to)
    )
    missing_before = immediately_missing_before(current_invoice) if current_invoice else []

    if queue.state == "duplicate":
        risk = "DUPLICATE_REF_STOPPED"
    elif queue.attempts > 1 and current_invoice and missing_before:
        risk = "DUP_RISK_RETRY_PLUS_GAP"
    elif queue.attempts > 1 and queue.state == "done":
        risk = "RETRY_DONE_NO_ADJACENT_GAP"
    elif queue.attempts > 1:
        risk = "RETRY_NOT_DONE"
    elif processed_outside:
        risk = "PROCESSED_OUTSIDE_WINDOW"
    elif created_outside:
        risk = "NORMAL_DEFERRED"
    else:
        risk = "NORMAL"

    risk_groups[risk].append(queue)
    queue_rows.append((
        queue,
        order,
        current_invoice,
        risk,
        created_outside,
        processed_outside,
        missing_before,
    ))

if SHOW_ALL_QUEUES:
    print("\n[3] TAT CA QUEUE TAO HOAC XU LY TRONG THANG: %s" % len(queue_rows))
    for (
        queue,
        order,
        current_invoice,
        risk,
        created_outside,
        processed_outside,
        missing_before,
    ) in queue_rows:
        print(
            "  [%s] Q%s attempts=%s state=%s | create_local=%s%s | "
            "processed_local=%s%s | SO=%s(id=%s) | Shopee=%s | inv=%s"
            % (
                risk,
                queue.id,
                queue.attempts,
                queue.state,
                local_text(queue.create_date),
                " OUTSIDE->DEFER" if created_outside else "",
                local_text(queue.processed_at),
                " OUTSIDE!" if processed_outside else "",
                order.name if order else "(missing)",
                order.id if order else "",
                queue.order_ref or "",
                current_invoice.inv_no if current_invoice else "(none)",
            )
        )
        if missing_before:
            print(
                "    adjacent_missing_before=%s"
                % ", ".join(str(number).zfill(8) for number in missing_before)
            )
        if queue.error_msg:
            print("    last_error=%s" % " ".join(queue.error_msg.split())[:300])

print("\n[4] RETRY / RISK CAN KIEM TRA")
review_keys = (
    "DUP_RISK_RETRY_PLUS_GAP",
    "DUPLICATE_REF_STOPPED",
    "RETRY_DONE_NO_ADJACENT_GAP",
    "RETRY_NOT_DONE",
    "PROCESSED_OUTSIDE_WINDOW",
)
for key in review_keys:
    rows = [row for row in queue_rows if row[3] == key]
    print("\n  %s: %s" % (key, len(rows)))
    for queue, order, current_invoice, _, created_outside, processed_outside, missing_before in rows:
        print(
            "    Q%s attempts=%s state=%s | create=%s%s | processed=%s%s | "
            "SO=%s | Shopee=%s | current_inv=%s | missing_before=%s"
            % (
                queue.id,
                queue.attempts,
                queue.state,
                local_text(queue.create_date),
                " (deferred expected)" if created_outside else "",
                local_text(queue.processed_at),
                " (outside!)" if processed_outside else "",
                order.name if order else "(missing)",
                queue.order_ref or "",
                current_invoice.inv_no if current_invoice else "(none)",
                (
                    ",".join(str(number).zfill(8) for number in missing_before)
                    if missing_before else "(none)"
                ),
            )
        )
        if current_invoice:
            print(
                "      inv_date=%s/%s code=%s transaction=%s total=%s"
                % (
                    current_invoice.inv_date or "",
                    current_invoice.inv_date_result or "",
                    current_invoice.inv_code or "",
                    current_invoice.transaction_id or "",
                    current_invoice.total_amount_oc,
                )
            )
        if order:
            print("      %s" % order_url(order))

# Durable duplicate records are not enough to find external orphan invoices, but are still anomalous.
duplicate_record_orders = []
for order in orders_seen:
    records = Invoice.search([("sale_order_id", "=", order.id)])
    published = records.filtered(lambda inv: inv.state not in ("draft", "cancelled"))
    if len(published) > 1:
        duplicate_record_orders.append((order, published))

print("\n[5] SO CO NHIEU HON 1 HOA DON PUBLISHED CON TON TAI TRONG ODOO: %s" % (
    len(duplicate_record_orders),
))
for order, records in duplicate_record_orders:
    print("  SO=%s id=%s | Shopee=%s | invoices=%s" % (
        order.name,
        order.id,
        getattr(order, "shopee_order_ref", "") or "",
        ", ".join("%s(id=%s)" % (inv.inv_no or "(no number)", inv.id) for inv in records),
    ))
    print("    %s" % order_url(order))

print("\n" + "=" * 150)
print("SUMMARY THANG %s" % MONTH)
print("=" * 150)
print("Invoices in month                  : %s" % len(invoices))
print("Queues created/processed in month : %s" % len(queues))
print("NORMAL                            : %s" % len(risk_groups["NORMAL"]))
print("NORMAL_DEFERRED                   : %s" % len(risk_groups["NORMAL_DEFERRED"]))
print("DUP_RISK_RETRY_PLUS_GAP           : %s" % len(risk_groups["DUP_RISK_RETRY_PLUS_GAP"]))
print("DUPLICATE_REF_STOPPED             : %s" % len(risk_groups["DUPLICATE_REF_STOPPED"]))
print("RETRY_DONE_NO_ADJACENT_GAP        : %s" % len(risk_groups["RETRY_DONE_NO_ADJACENT_GAP"]))
print("RETRY_NOT_DONE                    : %s" % len(risk_groups["RETRY_NOT_DONE"]))
print("PROCESSED_OUTSIDE_WINDOW          : %s" % len(risk_groups["PROCESSED_OUTSIDE_WINDOW"]))
print("SO with >1 published Odoo records : %s" % len(duplicate_record_orders))
for key in review_keys:
    for queue in risk_groups[key]:
        order = queue.sale_order_id
        print(
            "  REVIEW %-30s Q%s attempts=%s SO=%s Shopee=%s inv=%s"
            % (
                key,
                queue.id,
                queue.attempts,
                order.name if order else "(missing)",
                queue.order_ref or "",
                queue.meinvoice_invoice_id.inv_no or "(none)",
            )
        )
print("=" * 150)
print(
    "Gaps chi co nghia la so khong con trong Odoo; co the la invoice orphan, "
    "invoice tao ngoai Odoo, hoac ban ghi da bi xoa."
)
print("Script chi doc du lieu, khong write/unlink/commit.")
