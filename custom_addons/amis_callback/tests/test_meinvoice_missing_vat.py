# -*- coding: utf-8 -*-
import json
from datetime import date
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestMeInvoiceMissingVat(TransactionCase):
    """Đơn có dòng không VAT: không ra HĐĐT nháp, không được gửi CQT."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env['amis.callback.config'].sudo().ensure_singleton()
        cls.config.write({'meinvoice_enabled': True, 'meinvoice_inv_series': '1C26MLV'})
        cls.vat8 = cls.env['account.tax'].create({
            'name': 'VAT test 8%', 'amount': 8.0, 'amount_type': 'percent', 'type_tax_use': 'sale',
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Khách test VAT'})
        cls.product_vat = cls.env['product.product'].create({
            'name': 'Hàng có VAT', 'default_code': 'TEST-VAT', 'taxes_id': [(6, 0, cls.vat8.ids)],
        })
        cls.product_no_vat = cls.env['product.product'].create({
            'name': 'Hàng không VAT', 'default_code': 'TEST-NOVAT', 'taxes_id': [(5, 0, 0)],
        })

    def _order(self, *products):
        return self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'state': 'sale',
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': 1,
                'price_unit': 108000,
                'tax_id': [(6, 0, product.taxes_id.ids)],
            }) for product in products],
        })

    def _draft(self, order):
        return self.env['meinvoice.invoice'].create({
            'sale_order_id': order.id,
            'inv_series': '1C26MLV',
            'inv_date': date.today(),
            'invoice_data_json': json.dumps({'RefID': 'vat-test-ref', 'InvSeries': '1C26MLV'}),
        })

    def test_vat_error_lists_only_lines_without_vat(self):
        self.assertEqual(self._order(self.product_vat)._meinvoice_vat_error(), '')
        error = self._order(self.product_vat, self.product_no_vat)._meinvoice_vat_error()
        self.assertIn('Hàng không VAT', error)
        self.assertNotIn('Hàng có VAT', error)

    def _create_from_order(self, order):
        # shopee_order_ref thuộc module ngoài — giả lập đơn Shopee thay vì ghi field.
        with patch.object(type(order), '_is_meinvoice_shopee_order', return_value=True):
            order.action_publish_meinvoice_invoice()
        return order.amis_draft_invoice_ids

    def test_create_from_order_marks_invalid_instead_of_draft(self):
        invoice = self._create_from_order(self._order(self.product_vat, self.product_no_vat))
        self.assertEqual(invoice.state, 'invalid')
        self.assertIn('Hàng không VAT', invoice.invalid_reason)

    def test_create_from_order_with_vat_is_draft(self):
        invoice = self._create_from_order(self._order(self.product_vat))
        self.assertEqual(invoice.state, 'draft')

    def test_non_shopee_order_cannot_create_invoice(self):
        order = self._order(self.product_vat)
        with patch.object(type(order), '_is_meinvoice_shopee_order', return_value=False):
            with self.assertRaises(UserError):
                order.action_publish_meinvoice_invoice()
        self.assertFalse(order.amis_draft_invoice_ids)

    def test_invalid_invoice_cannot_be_sent(self):
        invoice = self._draft(self._order(self.product_no_vat))
        invoice.write({'state': 'invalid', 'invalid_reason': 'thiếu VAT'})
        with patch.object(type(self.config), 'push_meinvoice_invoice') as push:
            with self.assertRaises(UserError):
                invoice.action_publish()
        push.assert_not_called()
        self.assertEqual(invoice.state, 'invalid')

    def test_old_draft_missing_vat_turns_invalid_on_publish(self):
        # Nháp tạo trước khi có quy tắc: lúc gửi mới phát hiện, không được gọi meInvoice.
        invoice = self._draft(self._order(self.product_no_vat))
        with patch.object(type(self.config), 'push_meinvoice_invoice') as push:
            result = invoice.action_publish()
        push.assert_not_called()
        self.assertEqual(invoice.state, 'invalid')
        self.assertEqual(result['tag'], 'display_notification')

    def test_queue_stops_with_invalid_state(self):
        order = self._order(self.product_no_vat)
        invoice = self._draft(order)
        queue = self.env['amis.webhook.queue'].create({
            'order_ref': 'TEST-NOVAT', 'sale_order_id': order.id,
            'trigger_status': 'COMPLETED', 'state': 'pending',
        })
        with patch.object(type(self.config), 'push_meinvoice_invoice') as push:
            queue._process_one(self.config)
        push.assert_not_called()
        self.assertEqual(invoice.state, 'invalid')
        self.assertEqual(queue.state, 'invalid')
        self.assertEqual(queue.meinvoice_invoice_id, invoice)
        self.assertIn('INVALID', queue.attempt_history)
