# -*- coding: utf-8 -*-
import json


TERMINAL_STATES = {'delete_pending', 'manual_delete_required', 'deleted'}


def _callback_item(raw_json):
    try:
        item = json.loads(raw_json or '{}')
    except (TypeError, ValueError):
        return {}
    return item if isinstance(item, dict) else {}


def migrate(cr, version):
    """Backfill existing payment requests without casting legacy JSON in SQL."""
    cr.execute("""
        SELECT id, name, org_refid, state
          FROM amis_payment_request
         WHERE COALESCE(BTRIM(org_refid), '') != ''
    """)
    payments = {row['id']: row for row in cr.dictfetchall()}
    if not payments:
        return

    payment_ids_by_org_refid = {}
    payment_ids_by_name = {}
    for payment_id, payment in payments.items():
        org_refid = (payment.get('org_refid') or '').strip()
        name = (payment.get('name') or '').strip()
        if org_refid:
            payment_ids_by_org_refid.setdefault(org_refid, set()).add(payment_id)
        if name:
            payment_ids_by_name.setdefault(name, set()).add(payment_id)

    cr.execute("""
        SELECT callback_line.org_refid,
               callback_line.raw_json,
               callback_line.success,
               callback_log.data_type,
               callback_log.received_at
          FROM amis_callback_log_line callback_line
          JOIN amis_callback_log callback_log
            ON callback_log.id = callback_line.log_id
         ORDER BY callback_log.received_at DESC, callback_line.id DESC
    """)

    latest_by_payment = {}
    approved_payment_ids = set()
    for callback in cr.dictfetchall():
        item = _callback_item(callback.get('raw_json'))
        org_refid = (callback.get('org_refid') or '').strip()
        org_refno = (item.get('org_refno') or item.get('refno') or '').strip()
        matched_ids = set(payment_ids_by_org_refid.get(org_refid, ()))
        matched_ids.update(payment_ids_by_name.get(org_refno, ()))
        for payment_id in matched_ids:
            latest_by_payment.setdefault(payment_id, callback)
            if callback.get('data_type') == 18 and callback.get('success'):
                approved_payment_ids.add(payment_id)

    updates = []
    for payment_id, callback in latest_by_payment.items():
        payment = payments[payment_id]
        current_state = payment.get('state') or 'draft'
        data_type = int(callback.get('data_type') or 0)
        success = bool(callback.get('success'))
        new_state = current_state
        if current_state not in TERMINAL_STATES:
            if payment_id in approved_payment_ids:
                new_state = 'approved'
            elif data_type in (1, 3) and success and current_state != 'approved':
                new_state = 'request_accepted'
            elif not success:
                new_state = 'error'
        updates.append((
            data_type,
            new_state,
            callback.get('received_at'),
            payment_id,
        ))

    if updates:
        cr.executemany("""
            UPDATE amis_payment_request
               SET callback_data_type = %s,
                   state = %s,
                   state_updated_at = COALESCE(%s, state_updated_at)
             WHERE id = %s
        """, updates)
