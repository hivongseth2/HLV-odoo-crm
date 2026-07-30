# -*- coding: utf-8 -*-
"""
Read-only audit of meInvoice invoices and deletion traces in a local date range.

Odoo.sh:
    odoo-bin shell -d "$PGDATABASE" --no-http < bin/audit_meinvoice_date_range.py

Optional:
    DATE_FROM=2026-07-16 DATE_TO=2026-07-17 \
    odoo-bin shell -d "$PGDATABASE" --no-http < bin/audit_meinvoice_date_range.py
"""

import os
import re
import unicodedata
from datetime import datetime, time, timedelta

from odoo import fields


DATE_FROM = os.environ.get("DATE_FROM") or "2026-07-16"
DATE_TO = os.environ.get("DATE_TO") or "2026-07-17"
LOCAL_UTC_OFFSET_HOURS = int(os.environ.get("LOCAL_UTC_OFFSET_HOURS") or "7")

TARGET_NO = (os.environ.get("INVOICE_NO") or "00005928").strip()
TARGET_CODE = (
    os.environ.get("INVOICE_CODE") or "M1-26-WJ1VA-00000005966"
).strip()
TARGET_SKU = (os.environ.get("SKU") or "48-22-8902").strip()
TARGET_TOTAL = float(os.environ.get("TOTAL") or "144061")
TARGET_TOLERANCE = float(os.environ.get("AMOUNT_TOLERANCE") or "1")


def parse_date(value, label):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise SystemExit("%s phai co dang YYYY-MM-DD, dang nhan: %s" % (label, value))


def model_exists(model_name):
    return model_name in env.registry.models  # noqa: F821


def local_datetime(value):
    if not value:
        return ""
    dt = fields.Datetime.to_datetime(value)
    return fields.Datetime.to_string(dt + timedelta(hours=LOCAL_UTC_OFFSET_HOURS))


def one_line(value, limit=220):
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def ascii_fold(value):
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.replace("đ", "d").replace("Đ", "D").upper()


def invoice_exists(invoice_id):
    if not invoice_id or not model_exists("meinvoice.invoice"):
        return False
    return bool(env["meinvoice.invoice"].sudo().browse(invoice_id).exists())  # noqa: F821


def order_has_target_facts(order):
    if not order:
        return False
    amount_match = abs(float(order.amount_total or 0.0) - TARGET_TOTAL) <= TARGET_TOLERANCE
    sku_match = any(
        (line.product_id.default_code or "").strip() == TARGET_SKU
        for line in order.order_line
    )
    return amount_match and sku_match


def order_url(order):
    return "%s/web#id=%s&model=sale.order&view_type=form" % (
        base_url,
        order.id,
    )


date_from = parse_date(DATE_FROM, "DATE_FROM")
date_to = parse_date(DATE_TO, "DATE_TO")
if date_to < date_from:
    raise SystemExit("DATE_TO phai >= DATE_FROM")

date_to_exclusive = date_to + timedelta(days=1)
utc_from = datetime.combine(date_from, time.min) - timedelta(
    hours=LOCAL_UTC_OFFSET_HOURS
)
utc_to = datetime.combine(date_to_exclusive, time.min) - timedelta(
    hours=LOCAL_UTC_OFFSET_HOURS
)
utc_from_text = fields.Datetime.to_string(utc_from)
utc_to_text = fields.Datetime.to_string(utc_to)

base_url = (
    env["ir.config_parameter"].sudo().get_param("web.base.url")  # noqa: F821
    or ""
).rstrip("/")

print("=" * 130)
print("AUDIT HOA DON meInvoice NGAY %s -> %s (GIO UTC+%s, READ-ONLY)" % (
    DATE_FROM,
    DATE_TO,
    LOCAL_UTC_OFFSET_HOURS,
))
print("=" * 130)
print("UTC domain : >= %s and < %s" % (utc_from_text, utc_to_text))
print("Target     : no=%s | code=%s | total=%s | SKU=%s" % (
    TARGET_NO,
    TARGET_CODE,
    TARGET_TOTAL,
    TARGET_SKU,
))

# 1. Durable invoice records, using both requested invoice date and returned invoice date.
invoices = None
invoice_reason = {}
if model_exists("meinvoice.invoice"):
    Invoice = env["meinvoice.invoice"].sudo()  # noqa: F821
    invoices = Invoice.browse()

    for field_name in ("inv_date", "inv_date_result"):
        if field_name not in Invoice._fields:
            continue
        found = Invoice.search([
            (field_name, ">=", DATE_FROM),
            (field_name, "<=", DATE_TO),
        ])
        invoices |= found
        for inv in found:
            invoice_reason.setdefault(inv.id, []).append("%s in range" % field_name)

    # Include records created during the local interval even if their invoice date was later reset.
    created = Invoice.search([
        ("create_date", ">=", utc_from_text),
        ("create_date", "<", utc_to_text),
    ])
    invoices |= created
    for inv in created:
        invoice_reason.setdefault(inv.id, []).append("create_date in range")

    print("\n[1] meinvoice.invoice con ton tai: %s" % len(invoices))
    if not invoices:
        print("  Khong co ban ghi.")
    for inv in invoices.sorted(key=lambda record: (record.inv_date or date_from, record.id)):
        series = (
            getattr(inv, "inv_series_result", False)
            or getattr(inv, "inv_series", False)
            or ""
        )
        target_mark = ""
        if (
            (getattr(inv, "inv_no", "") or "") in (TARGET_NO, TARGET_NO.lstrip("0"))
            or (getattr(inv, "inv_code", "") or "") == TARGET_CODE
        ):
            target_mark = "  <<< TARGET EXACT"
        print(
            "  INV id=%s | create_local=%s | date=%s/%s | state=%s | "
            "series=%s | no=%s | code=%s | total=%s | SO=%s%s"
            % (
                inv.id,
                local_datetime(inv.create_date),
                getattr(inv, "inv_date", "") or "",
                getattr(inv, "inv_date_result", "") or "",
                getattr(inv, "state", "") or "",
                series,
                getattr(inv, "inv_no", "") or "",
                getattr(inv, "inv_code", "") or "",
                getattr(inv, "total_amount_oc", "") or "",
                inv.sale_order_id.name if inv.sale_order_id else "(missing)",
                target_mark,
            )
        )
        print("    reason=%s" % "; ".join(invoice_reason.get(inv.id, [])))
        if inv.sale_order_id:
            print("    %s" % order_url(inv.sale_order_id))
else:
    print("\n[1] Model meinvoice.invoice khong ton tai.")

# 2. Duplicated result fields on sale.order survive invoice deletion unless manually reset.
SaleOrder = env["sale.order"].sudo()  # noqa: F821
orders_by_invoice_date = SaleOrder.browse()
if "misa_meinvoice_inv_date" in SaleOrder._fields:
    orders_by_invoice_date = SaleOrder.search([
        ("misa_meinvoice_inv_date", ">=", DATE_FROM),
        ("misa_meinvoice_inv_date", "<=", DATE_TO),
    ], order="misa_meinvoice_inv_date, id")

print("\n[2] sale.order con giu ket qua meInvoice trong ngay: %s" % len(orders_by_invoice_date))
if not orders_by_invoice_date:
    print("  Khong co ban ghi.")
for order in orders_by_invoice_date:
    target_mark = ""
    if (
        (getattr(order, "misa_meinvoice_inv_no", "") or "") in (
            TARGET_NO,
            TARGET_NO.lstrip("0"),
        )
        or (getattr(order, "misa_meinvoice_inv_code", "") or "") == TARGET_CODE
    ):
        target_mark = "  <<< TARGET EXACT"
    print(
        "  SO=%s id=%s | inv_date=%s | series=%s | no=%s | code=%s | "
        "transaction=%s | total=%s | Shopee=%s%s"
        % (
            order.name,
            order.id,
            getattr(order, "misa_meinvoice_inv_date", "") or "",
            getattr(order, "misa_meinvoice_inv_series", "") or "",
            getattr(order, "misa_meinvoice_inv_no", "") or "",
            getattr(order, "misa_meinvoice_inv_code", "") or "",
            getattr(order, "misa_meinvoice_transaction_id", "") or "",
            order.amount_total,
            getattr(order, "shopee_order_ref", "") or "",
            target_mark,
        )
    )
    print("    %s" % order_url(order))

# 3. Webhook queue is the best surviving link for an automatically published, then deleted invoice.
queues = None
suspected_deleted_queues = []
target_queue_orders = SaleOrder.browse()
if model_exists("amis.webhook.queue"):
    Queue = env["amis.webhook.queue"].sudo()  # noqa: F821
    queues = Queue.browse()
    for field_name in ("create_date", "processed_at"):
        found = Queue.search([
            (field_name, ">=", utc_from_text),
            (field_name, "<", utc_to_text),
        ])
        queues |= found

    print("\n[3] amis.webhook.queue tao/xu ly trong khoang ngay: %s" % len(queues))
    if not queues:
        print("  Khong co queue.")
    for queue in queues.sorted(key=lambda record: (record.processed_at or record.create_date, record.id)):
        order = queue.sale_order_id
        linked_invoice_id = queue.meinvoice_invoice_id.id
        target_facts = order_has_target_facts(order)
        if target_facts:
            target_queue_orders |= order
        deleted_suspect = (
            queue.state in ("done", "skipped")
            and not linked_invoice_id
            and (
                queue.state == "done"
                or "DA CO HDDT" in ascii_fold(queue.error_msg)
                or "DA CO HOA DON" in ascii_fold(queue.error_msg)
            )
        )
        if deleted_suspect:
            suspected_deleted_queues.append(queue)

        marks = []
        if target_facts:
            marks.append("TARGET FACTS")
        if deleted_suspect:
            marks.append("POSSIBLY DELETED INVOICE")
        mark_text = ("  <<< " + ", ".join(marks)) if marks else ""

        print(
            "  Q id=%s | state=%s attempts=%s | create_local=%s | processed_local=%s | "
            "SO=%s(id=%s) | Shopee=%s | invoice_id=%s | amount=%s%s"
            % (
                queue.id,
                queue.state,
                queue.attempts,
                local_datetime(queue.create_date),
                local_datetime(queue.processed_at),
                order.name if order else "(missing)",
                order.id if order else "",
                queue.order_ref or "",
                linked_invoice_id or "(empty)",
                order.amount_total if order else "",
                mark_text,
            )
        )
        if queue.error_msg:
            print("    note=%s" % one_line(queue.error_msg))
        if order:
            print("    %s" % order_url(order))
else:
    print("\n[3] Model amis.webhook.queue khong ton tai.")

# 4. Sent mail is auto_delete=False and can retain the invoice number after invoice deletion.
mail_records = None
if model_exists("mail.mail"):
    Mail = env["mail.mail"].sudo()  # noqa: F821
    mail_domain = [
        ("create_date", ">=", utc_from_text),
        ("create_date", "<", utc_to_text),
    ]
    if "model" in Mail._fields:
        mail_domain.append(("model", "=", "meinvoice.invoice"))
    mail_records = Mail.search(mail_domain, order="create_date, id")

    print("\n[4] mail.mail cua meinvoice.invoice trong khoang ngay: %s" % len(mail_records))
    if not mail_records:
        print("  Khong co mail.")
    for mail in mail_records:
        subject = mail.subject or ""
        body = getattr(mail, "body_html", "") or ""
        target_mark = ""
        if TARGET_NO in subject or TARGET_NO in body or TARGET_CODE in body:
            target_mark = "  <<< TARGET EXACT"
        exists = invoice_exists(mail.res_id)
        orphan_mark = " ORPHAN/INVOICE DELETED" if mail.res_id and not exists else ""
        print(
            "  MAIL id=%s | local=%s | state=%s | invoice_res_id=%s (%s%s) | to=%s%s"
            % (
                mail.id,
                local_datetime(mail.create_date),
                mail.state,
                mail.res_id or "",
                "exists" if exists else "missing",
                orphan_mark,
                mail.email_to or "",
                target_mark,
            )
        )
        print("    subject=%s" % one_line(subject))

# 5. Generic attachments can also survive as orphaned records and preserve the PDF filename.
attachments = None
if model_exists("ir.attachment"):
    Attachment = env["ir.attachment"].sudo()  # noqa: F821
    attachments = Attachment.search([
        ("res_model", "=", "meinvoice.invoice"),
        ("create_date", ">=", utc_from_text),
        ("create_date", "<", utc_to_text),
    ], order="create_date, id")

    print("\n[5] ir.attachment cua meinvoice.invoice trong khoang ngay: %s" % len(attachments))
    if not attachments:
        print("  Khong co attachment.")
    for attachment in attachments:
        exists = invoice_exists(attachment.res_id)
        target_mark = ""
        if TARGET_NO in (attachment.name or "") or TARGET_CODE in (attachment.name or ""):
            target_mark = "  <<< TARGET"
        print(
            "  ATT id=%s | local=%s | invoice_res_id=%s (%s) | name=%s%s"
            % (
                attachment.id,
                local_datetime(attachment.create_date),
                attachment.res_id or "",
                "exists" if exists else "ORPHAN/INVOICE DELETED",
                attachment.name or "",
                target_mark,
            )
        )

# 6. Database-backed server logs, if log_db was enabled on Odoo.sh.
logging_records = None
if model_exists("ir.logging"):
    Logging = env["ir.logging"].sudo()  # noqa: F821
    logging_records = Logging.search([
        ("create_date", ">=", utc_from_text),
        ("create_date", "<", utc_to_text),
        "|",
        ("message", "ilike", "meInvoice"),
        ("message", "ilike", TARGET_NO),
    ], order="create_date, id")

    print("\n[6] ir.logging lien quan meInvoice (chi co neu Odoo bat log_db): %s" % len(logging_records))
    if not logging_records:
        print("  Khong co log_db.")
    for log in logging_records:
        target_mark = ""
        message = log.message or ""
        if TARGET_NO in message or TARGET_CODE in message:
            target_mark = "  <<< TARGET EXACT"
        print(
            "  LOG id=%s | local=%s | level=%s | %s%s"
            % (
                log.id,
                local_datetime(log.create_date),
                log.level,
                one_line(message, 500),
                target_mark,
            )
        )

print("\n" + "=" * 130)
print("TOM TAT DAU VET")
print("=" * 130)
print("Invoice records con ton tai trong range : %s" % len(invoices or []))
print("Sale orders con field ket qua trong range: %s" % len(orders_by_invoice_date))
print("Queues trong range                     : %s" % len(queues or []))
print("Queue nghi invoice da bi xoa            : %s" % len(suspected_deleted_queues))
print("Mail trong range                        : %s" % len(mail_records or []))
print("Attachment trong range                  : %s" % len(attachments or []))
print("Log DB trong range                      : %s" % len(logging_records or []))
print("SO queue khop target total + SKU        : %s" % len(target_queue_orders))
for order in target_queue_orders:
    print(
        "  TARGET CANDIDATE FROM QUEUE: %s id=%s | Shopee=%s | %s"
        % (
            order.name,
            order.id,
            getattr(order, "shopee_order_ref", "") or "",
            order_url(order),
        )
    )
print("=" * 130)
print("Script chi doc du lieu, khong write/unlink/commit.")
