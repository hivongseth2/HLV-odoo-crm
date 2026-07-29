# -*- coding: utf-8 -*-
import json

from odoo.tests.common import TransactionCase


class TestSaVoucherCallback(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'SAVoucher callback customer'})

    def _create_order(self, org_refid):
        return self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'misa_sa_voucher_org_refid': org_refid,
        })

    def _create_callback_line(self, org_refid, success, error_message=''):
        log = self.env['amis.callback.log'].create({
            'data_type': 1,
            'signature_valid': True,
            'state': 'validated',
        })
        return self.env['amis.callback.log.line'].create({
            'log_id': log.id,
            'org_refid': org_refid,
            'success': success,
            'error_message': error_message,
            'voucher_type': 13,
            'raw_json': json.dumps({
                'org_refid': org_refid,
                'success': success,
                'error_message': error_message,
                'voucher_type': 13,
            }),
        })

    def test_success_callback_marks_sa_voucher_synced(self):
        order = self._create_order('11111111-1111-1111-1111-111111111111')

        self._create_callback_line(order.misa_sa_voucher_org_refid, True)

        self.assertTrue(order.misa_sa_voucher_synced)

    def test_error_callback_resets_flag_and_requeues_outgoing_job(self):
        order = self._create_order('22222222-2222-2222-2222-222222222222')
        order.misa_sa_voucher_synced = True
        job = self.env['amis.sync.job'].create({
            'sale_order_id': order.id,
            'direction': 'outgoing',
            'status': 'done',
        })

        self._create_callback_line(
            order.misa_sa_voucher_org_refid,
            False,
            'Invalid SAVoucher payload',
        )

        self.assertFalse(order.misa_sa_voucher_synced)
        self.assertEqual(job.status, 'pending')
        self.assertEqual(job.retry_count, 1)
        self.assertEqual(job.error_msg, 'Invalid SAVoucher payload')
