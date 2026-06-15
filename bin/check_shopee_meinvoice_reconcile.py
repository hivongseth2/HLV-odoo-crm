# -*- coding: utf-8 -*-
"""
Check Shopee sale orders against non-cancelled meInvoice invoices.

Run inside Odoo shell:

    odoo-bin shell -c <odoo.conf> -d <db_name> --no-http < bin/check_shopee_meinvoice_reconcile.py

Or override inputs before exec:

    START_DATE = '2026-06-01'
    END_DATE = '2026-06-15'
    LIMIT = 20
    exec(open('bin/check_shopee_meinvoice_reconcile.py', encoding='utf-8').read())

Environment variables are also supported:

    $env:START_DATE='2026-06-01'
    $env:END_DATE='2026-06-15'
    $env:LIMIT='20'
    odoo-bin shell -c <odoo.conf> -d <db_name> --no-http < bin/check_shopee_meinvoice_reconcile.py

Date inputs are local business dates in UTC+7. Odoo stores date_order as UTC,
so the search domain subtracts 7 hours from the local date boundaries.
"""

import os
from datetime import datetime, time, timedelta

from odoo import fields


DEFAULT_START_DATE = '2026-05-01'
DEFAULT_END_DATE = '2026-06-15'
LOCAL_UTC_OFFSET_HOURS = 7
DEFAULT_LIMIT = 20
DEFAULT_TOLERANCE = 1.0

START_DATE = globals().get('START_DATE') or os.environ.get('START_DATE') or DEFAULT_START_DATE
END_DATE = globals().get('END_DATE') or os.environ.get('END_DATE') or DEFAULT_END_DATE
LIMIT = int(globals().get('LIMIT') or os.environ.get('LIMIT') or DEFAULT_LIMIT)
TOLERANCE = float(globals().get('TOLERANCE') or os.environ.get('TOLERANCE') or DEFAULT_TOLERANCE)
SHOW_OK = str(globals().get('SHOW_OK') or os.environ.get('SHOW_OK') or '1').lower() not in ('0', 'false', 'no')


def parse_local_date(value, label):
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        raise SystemExit('[ERROR] %s must use YYYY-MM-DD, got: %s' % (label, value))


def to_utc_string(dt_local):
    dt_utc = dt_local - timedelta(hours=LOCAL_UTC_OFFSET_HOURS)
    return fields.Datetime.to_string(dt_utc)


def money(value):
    return '{:,.2f}'.format(float(value or 0.0))


def local_dt_text(value):
    if not value:
        return ''
    dt_value = fields.Datetime.to_datetime(value)
    return fields.Datetime.to_string(dt_value + timedelta(hours=LOCAL_UTC_OFFSET_HOURS))


def first(value, length):
    text = str(value or '')
    return text[:length]


def invoice_label(inv):
    if not inv:
        return ''
    parts = []
    if inv.inv_series:
        parts.append(inv.inv_series)
    if inv.inv_no:
        parts.append(inv.inv_no)
    if inv.state:
        parts.append(inv.state)
    return ' '.join(parts) or ('id=%s' % inv.id)


start_date = parse_local_date(START_DATE, 'START_DATE')
end_date = parse_local_date(END_DATE, 'END_DATE')
if end_date < start_date:
    raise SystemExit('[ERROR] END_DATE must be >= START_DATE')

start_local = datetime.combine(start_date, time.min)
end_exclusive_local = datetime.combine(end_date + timedelta(days=1), time.min)
date_from_utc = to_utc_string(start_local)
date_to_utc = to_utc_string(end_exclusive_local)

SaleOrder = env['sale.order'].sudo()  # noqa: F821
Invoice = env['meinvoice.invoice'].sudo()  # noqa: F821

domain = [
    ('shopee_order_ref', '!=', False),
    ('shopee_order_ref', '!=', ''),
    ('date_order', '>=', date_from_utc),
    ('date_order', '<', date_to_utc),
]

orders = SaleOrder.search(domain, order='date_order asc, id asc', limit=LIMIT)

print('=' * 120)
print('Shopee sale order vs meInvoice check')
print('=' * 120)
print('Local date range UTC+7 : %s 00:00:00 -> %s 23:59:59' % (START_DATE, END_DATE))
print('Odoo UTC domain        : date_order >= %s and < %s' % (date_from_utc, date_to_utc))
print('Limit                  : %s' % LIMIT)
print('Amount tolerance        : %s VND' % TOLERANCE)
print('Orders fetched          : %s' % len(orders))
print()

header = (
    '%-9s %-18s %-19s %14s %5s %14s %14s %-18s %-28s'
    % (
        'SO',
        'ShopeeRef',
        'OrderDate+7',
        'OrderTotal',
        'Invs',
        'InvTotal',
        'Delta',
        'Status',
        'Invoice',
    )
)
print(header)
print('-' * len(header))

summary = {
    'ok': 0,
    'missing_invoice': 0,
    'amount_mismatch': 0,
    'multiple_invoice': 0,
}

problem_rows = []

for so in orders:
    invoices = Invoice.search([
        ('sale_order_id', '=', so.id),
        ('state', '!=', 'cancelled'),
    ], order='create_date asc, id asc')

    inv_count = len(invoices)
    inv_total = sum(invoices.mapped('total_amount_oc')) if invoices else 0.0
    order_total = float(so.amount_total or 0.0)
    delta = round(inv_total - order_total, 2)

    if not invoices:
        status = 'MISSING_INVOICE'
        summary['missing_invoice'] += 1
    elif inv_count != 1:
        status = 'MULTIPLE_INVOICE'
        summary['multiple_invoice'] += 1
    elif abs(delta) > TOLERANCE:
        status = 'AMOUNT_MISMATCH'
        summary['amount_mismatch'] += 1
    else:
        status = 'OK'
        summary['ok'] += 1

    inv = invoices[:1]
    row = (
        '%-9s %-18s %-19s %14s %5s %14s %14s %-18s %-28s'
        % (
            first(so.name, 9),
            first(so.shopee_order_ref, 18),
            first(local_dt_text(so.date_order), 19),
            money(order_total),
            inv_count,
            money(inv_total),
            money(delta),
            status,
            first(invoice_label(inv), 28),
        )
    )

    if status == 'OK':
        if SHOW_OK:
            print(row)
    else:
        problem_rows.append(row)
        print(row)

print()
print('=' * 120)
print('Summary')
print('=' * 120)
print('OK                 : %s' % summary['ok'])
print('Missing invoice    : %s' % summary['missing_invoice'])
print('Amount mismatch    : %s' % summary['amount_mismatch'])
print('Multiple invoices  : %s' % summary['multiple_invoice'])
print()

if problem_rows:
    print('Problem rows only')
    print('-' * 120)
    for row in problem_rows:
        print(row)
else:
    print('No problem rows in fetched sample.')
