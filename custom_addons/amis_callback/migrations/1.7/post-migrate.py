# -*- coding: utf-8 -*-


def migrate(cr, version):
    """Backfill the latest callback and approval state for existing payment requests."""
    cr.execute("""
        WITH latest_callback AS (
            SELECT DISTINCT ON (payment.id)
                payment.id AS payment_request_id,
                callback_log.data_type,
                callback_line.success,
                callback_log.received_at
            FROM amis_payment_request payment
            JOIN amis_callback_log_line callback_line
              ON BTRIM(callback_line.org_refid) = BTRIM(payment.org_refid)
              OR BTRIM(callback_line.raw_json::jsonb ->> 'org_refno') = BTRIM(payment.name)
            JOIN amis_callback_log callback_log
              ON callback_log.id = callback_line.log_id
            WHERE COALESCE(BTRIM(payment.org_refid), '') != ''
            ORDER BY payment.id, callback_log.received_at DESC, callback_line.id DESC
        ),
        approved_callback AS (
            SELECT DISTINCT payment.id AS payment_request_id
            FROM amis_payment_request payment
            JOIN amis_callback_log_line callback_line
              ON BTRIM(callback_line.org_refid) = BTRIM(payment.org_refid)
              OR BTRIM(callback_line.raw_json::jsonb ->> 'org_refno') = BTRIM(payment.name)
            JOIN amis_callback_log callback_log
              ON callback_log.id = callback_line.log_id
            WHERE callback_log.data_type = 18
              AND callback_line.success IS TRUE
        )
        UPDATE amis_payment_request payment
           SET callback_data_type = latest.data_type,
               state = CASE
                   WHEN approved.payment_request_id IS NOT NULL
                        AND payment.state NOT IN (
                            'delete_pending', 'manual_delete_required', 'deleted'
                        )
                       THEN 'approved'
                   WHEN latest.data_type IN (1, 3)
                        AND latest.success IS TRUE
                        AND payment.state NOT IN (
                            'approved', 'delete_pending', 'manual_delete_required', 'deleted'
                        )
                       THEN 'request_accepted'
                   WHEN latest.success IS FALSE
                        AND payment.state NOT IN (
                            'delete_pending', 'manual_delete_required', 'deleted'
                        )
                       THEN 'error'
                   ELSE payment.state
               END,
               state_updated_at = COALESCE(latest.received_at, payment.state_updated_at)
          FROM latest_callback latest
          LEFT JOIN approved_callback approved
            ON approved.payment_request_id = latest.payment_request_id
         WHERE payment.id = latest.payment_request_id
    """)
