# -*- coding: utf-8 -*-
import json
from datetime import date
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from ..models.amis_sync_exceptions import MeInvoiceDuplicateRefError


class TestMeInvoiceSafety(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'meInvoice safety customer'})
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.partner.id,
            'state': 'sale',
        })
        cls.config = cls.env['amis.callback.config'].sudo().ensure_singleton()

    def _draft(self, ref_id='test-ref-id'):
        self.order.write({
            'misa_meinvoice_ref_id': ref_id,
            'misa_meinvoice_synced': False,
            'misa_meinvoice_transaction_id': False,
            'misa_meinvoice_inv_no': False,
            'misa_meinvoice_inv_code': False,
            'misa_meinvoice_inv_series': False,
            'misa_meinvoice_inv_date': False,
        })
        return self.env['meinvoice.invoice'].create({
            'sale_order_id': self.order.id,
            'inv_series': '1C26MLV',
            'inv_date': date.today(),
            'invoice_data_json': json.dumps({
                'RefID': ref_id,
                'InvSeries': '1C26MLV',
                'InvDate': date.today().isoformat(),
            }),
        })

    def test_duplicate_ref_stops_without_second_publish(self):
        invoice = self._draft()
        duplicate_result = [{
            'ErrorCode': 'DuplicateInvoiceRefID',
            'DescriptionErrorCode': 'Invoice RefID already exists',
        }]

        with patch.object(
            type(self.config),
            'push_meinvoice_invoice',
            return_value=duplicate_result,
        ) as push:
            with self.assertRaises(MeInvoiceDuplicateRefError):
                invoice.action_publish()

        self.assertEqual(push.call_count, 1)
        self.assertEqual(invoice.state, 'draft')
        self.assertEqual(
            json.loads(invoice.invoice_data_json)['RefID'],
            'test-ref-id',
        )
        self.assertEqual(self.order.misa_meinvoice_ref_id, 'test-ref-id')
        self.assertFalse(self.order.misa_meinvoice_synced)

    def test_published_invoice_cannot_be_deleted_or_reset(self):
        invoice = self._draft()
        invoice.write({
            'state': 'accepted',
            'inv_no': '00000001',
            'inv_code': 'CQT-1',
        })

        with self.assertRaises(UserError):
            invoice.unlink()
        with self.assertRaises(UserError):
            invoice.action_reset_to_draft()
        with self.assertRaises(UserError):
            self.order.action_reset_meinvoice_invoice()

        self.assertTrue(invoice.exists())
        self.assertEqual(invoice.state, 'accepted')

    def test_submitted_invoice_cannot_be_locally_cancelled(self):
        invoice = self._draft()
        invoice.write({
            'state': 'submitted',
            'transaction_id': 'TX-EXISTS-ON-MISA',
            'inv_no': '00000002',
        })

        with self.assertRaises(UserError):
            invoice.action_cancel()

        self.assertEqual(invoice.state, 'submitted')

    def test_duplicate_ref_moves_queue_to_manual_review_and_keeps_history(self):
        invoice = self._draft('queue-ref-id')
        queue = self.env['amis.webhook.queue'].create({
            'order_ref': 'TEST-SHOPEE-ORDER',
            'sale_order_id': self.order.id,
            'trigger_status': 'COMPLETED',
            'state': 'pending',
        })

        with patch.object(
            type(invoice),
            'action_publish',
            side_effect=MeInvoiceDuplicateRefError('duplicate test'),
        ):
            queue._process_one(self.config)

        self.assertEqual(queue.state, 'duplicate')
        self.assertEqual(queue.attempts, 1)
        self.assertIn('DUPLICATE_REF_STOPPED', queue.attempt_history)
        self.assertIn('queue-ref-id', queue.attempt_history)
        self.assertEqual(queue.last_attempt_ref_id, 'queue-ref-id')

        with self.assertRaises(UserError):
            queue.action_retry()
