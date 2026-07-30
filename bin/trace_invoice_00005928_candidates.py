# -*- coding: utf-8 -*-
"""
Read-only deep trace for invoice 00005928 candidates.

Odoo.sh:
    odoo-bin shell -d "$PGDATABASE" --no-http \
      < bin/trace_invoice_00005928_candidates.py
"""

from datetime import timedelta

from odoo import fields


TARGET_NO = "00005928"
TARGET_CODE = "M1-26-WJ1VA-00000005966"
TARGET_TOTAL = 144061.0
TARGET_SKU = "48-22-8902"
TOLERANCE = 1.0
UTC_OFFSET = 7


def local_dt(value):
    if not value:
        return ""
    return fields.Datetime.to_string(
        fields.Datetime.to_datetime(value) + timedelta(hours=UTC_OFFSET)
    )


def model_exists(name):
    return name in env.registry.models  # noqa: F821


def url(order):
    return "%s/web#id=%s&model=sale.order&view_type=form" % (
        base_url,
        order.id,
    )


base_url = (
    env["ir.config_parameter"].sudo().get_param("web.base.url")  # noqa: F821
    or ""
).rstrip("/")
SaleOrder = env["sale.order"].sudo()  # noqa: F821

candidates = SaleOrder.search([
    ("amount_total", ">=", TARGET_TOTAL - TOLERANCE),
    ("amount_total", "<=", TARGET_TOTAL + TOLERANCE),
    ("order_line.product_id.default_code", "=", TARGET_SKU),
], order="date_order, id")

Invoice = env["meinvoice.invoice"].sudo() if model_exists("meinvoice.invoice") else None  # noqa: F821
Queue = env["amis.webhook.queue"].sudo() if model_exists("amis.webhook.queue") else None  # noqa: F821

print("=" * 130)
print("DEEP TRACE HOA DON %s / %s" % (TARGET_NO, TARGET_CODE))
print("=" * 130)

print("\n[1] Day so hoa don lan can 5924 -> 5932")
if Invoice is not None:
    neighbors = Invoice.search([
        ("inv_no", "in", [
            "00005924", "00005925", "00005926", "00005927", "00005928",
            "00005929", "00005930", "00005931", "00005932",
        ]),
    ], order="inv_no, id")
    for inv in neighbors:
        print(
            "  no=%s | code=%s | date=%s | INV id=%s | SO=%s(id=%s) | "
            "total=%s | transaction=%s"
            % (
                inv.inv_no or "",
                inv.inv_code or "",
                inv.inv_date_result or inv.inv_date or "",
                inv.id,
                inv.sale_order_id.name if inv.sale_order_id else "(missing)",
                inv.sale_order_id.id if inv.sale_order_id else "",
                inv.total_amount_oc,
                inv.transaction_id or "",
            )
        )
missing_numbers = []
existing_numbers = set(neighbors.mapped("inv_no")) if Invoice is not None else set()
for number in ("00005927", "00005928", "00005929"):
    if number not in existing_numbers:
        missing_numbers.append(number)
print("  Missing in Odoo: %s" % ", ".join(missing_numbers))

print("\n[2] Tat ca don khop tong tien + SKU: %s" % len(candidates))
unresolved = SaleOrder.browse()
for order in candidates:
    invoices = (
        Invoice.search([("sale_order_id", "=", order.id)], order="create_date, id")
        if Invoice is not None else []
    )
    queues = (
        Queue.search([
            "|",
            ("sale_order_id", "=", order.id),
            ("order_ref", "=", getattr(order, "shopee_order_ref", "") or ""),
        ], order="create_date, id")
        if Queue is not None else []
    )
    pickings = order.picking_ids.sorted(
        key=lambda picking: (picking.date_done or picking.create_date, picking.id)
    )

    direct_no = getattr(order, "misa_meinvoice_inv_no", "") or ""
    direct_code = getattr(order, "misa_meinvoice_inv_code", "") or ""
    resolved = bool(invoices or direct_no or direct_code)
    if not resolved:
        unresolved |= order

    print("\n  %s id=%s | Shopee=%s | order_local=%s | state=%s | resolved=%s" % (
        order.name,
        order.id,
        getattr(order, "shopee_order_ref", "") or "",
        local_dt(order.date_order),
        order.state,
        "YES" if resolved else "NO",
    ))
    print("    customer=%s | write_local=%s" % (
        order.partner_id.display_name or "",
        local_dt(order.write_date),
    ))
    print(
        "    SO meInvoice: synced=%s date=%s series=%s no=%s code=%s "
        "transaction=%s ref_id=%s"
        % (
            getattr(order, "misa_meinvoice_synced", False),
            getattr(order, "misa_meinvoice_inv_date", "") or "",
            getattr(order, "misa_meinvoice_inv_series", "") or "",
            direct_no,
            direct_code,
            getattr(order, "misa_meinvoice_transaction_id", "") or "",
            getattr(order, "misa_meinvoice_ref_id", "") or "",
        )
    )

    if invoices:
        for inv in invoices:
            print(
                "    INV id=%s create_local=%s state=%s date=%s/%s no=%s "
                "code=%s transaction=%s"
                % (
                    inv.id,
                    local_dt(inv.create_date),
                    inv.state,
                    inv.inv_date or "",
                    inv.inv_date_result or "",
                    inv.inv_no or "",
                    inv.inv_code or "",
                    inv.transaction_id or "",
                )
            )
    else:
        print("    INV: NONE")

    if queues:
        for queue in queues:
            print(
                "    QUEUE id=%s create_local=%s processed_local=%s state=%s "
                "attempts=%s invoice_id=%s note=%s"
                % (
                    queue.id,
                    local_dt(queue.create_date),
                    local_dt(queue.processed_at),
                    queue.state,
                    queue.attempts,
                    queue.meinvoice_invoice_id.id or "(empty)",
                    " ".join((queue.error_msg or "").split())[:160],
                )
            )
    else:
        print("    QUEUE: NONE")

    if pickings:
        for picking in pickings:
            print(
                "    PICKING %s type=%s state=%s create_local=%s done_local=%s"
                % (
                    picking.name,
                    picking.picking_type_code or "",
                    picking.state,
                    local_dt(picking.create_date),
                    local_dt(picking.date_done),
                )
            )
    else:
        print("    PICKING: NONE")
    print("    %s" % url(order))

print("\n[3] Dau vet exact tren mail/message/attachment/log (khong gioi han ngay)")
trace_count = 0

if model_exists("mail.mail"):
    Mail = env["mail.mail"].sudo()  # noqa: F821
    mails = Mail.search([
        "|", "|",
        ("subject", "ilike", TARGET_NO),
        ("body_html", "ilike", TARGET_NO),
        ("body_html", "ilike", TARGET_CODE),
    ])
    for mail in mails:
        trace_count += 1
        print(
            "  MAIL id=%s create_local=%s res_id=%s state=%s subject=%s"
            % (
                mail.id,
                local_dt(mail.create_date),
                mail.res_id or "",
                mail.state,
                mail.subject or "",
            )
        )

if model_exists("mail.message"):
    Message = env["mail.message"].sudo()  # noqa: F821
    message_domain = [
        ("model", "=", "meinvoice.invoice"),
        "|", "|", "|",
        ("record_name", "ilike", TARGET_NO),
        ("subject", "ilike", TARGET_NO),
        ("body", "ilike", TARGET_NO),
        ("body", "ilike", TARGET_CODE),
    ]
    messages = Message.search(message_domain, order="date, id")
    for message in messages:
        trace_count += 1
        exists = bool(Invoice is not None and Invoice.browse(message.res_id).exists())
        print(
            "  MESSAGE id=%s date_local=%s old_invoice_id=%s invoice_exists=%s "
            "record_name=%s subject=%s"
            % (
                message.id,
                local_dt(message.date),
                message.res_id or "",
                exists,
                message.record_name or "",
                message.subject or "",
            )
        )

if model_exists("ir.attachment"):
    Attachment = env["ir.attachment"].sudo()  # noqa: F821
    attachments = Attachment.search([
        "|",
        ("name", "ilike", TARGET_NO),
        ("description", "ilike", TARGET_CODE),
    ])
    for attachment in attachments:
        trace_count += 1
        print(
            "  ATT id=%s create_local=%s res_model=%s res_id=%s name=%s"
            % (
                attachment.id,
                local_dt(attachment.create_date),
                attachment.res_model or "",
                attachment.res_id or "",
                attachment.name or "",
            )
        )

if model_exists("ir.logging"):
    Logging = env["ir.logging"].sudo()  # noqa: F821
    logs = Logging.search([
        "|",
        ("message", "ilike", TARGET_NO),
        ("message", "ilike", TARGET_CODE),
    ], order="create_date, id")
    for log in logs:
        trace_count += 1
        print(
            "  LOG id=%s local=%s level=%s message=%s"
            % (
                log.id,
                local_dt(log.create_date),
                log.level,
                " ".join((log.message or "").split())[:500],
            )
        )

if not trace_count:
    print("  Khong co dau vet exact.")

print("\n" + "=" * 130)
print("UNRESOLVED CANDIDATES (khong con invoice va SO result): %s" % len(unresolved))
for order in unresolved:
    print(
        "  %s id=%s | Shopee=%s | order_local=%s | customer=%s | %s"
        % (
            order.name,
            order.id,
            getattr(order, "shopee_order_ref", "") or "",
            local_dt(order.date_order),
            order.partner_id.display_name or "",
            url(order),
        )
    )
print("=" * 130)
print("Script chi doc du lieu, khong write/unlink/commit.")
