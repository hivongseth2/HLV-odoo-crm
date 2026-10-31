# -*- coding: utf-8 -*-
from datetime import datetime

import pytz

from odoo import api, fields, models


class MeinvoiceInvoicePos(models.Model):
    _inherit = 'meinvoice.invoice'

    pos_order_id = fields.Many2one(
        'pos.order', string='Đơn POS', ondelete='restrict', readonly=True, index='btree_not_null',
    )

    @api.depends('pos_order_id.partner_id')
    def _compute_partner_id(self):
        super()._compute_partner_id()
        for rec in self.filtered('pos_order_id'):
            rec.partner_id = rec.pos_order_id.partner_id

    @api.depends('pos_order_id')
    def _compute_name(self):
        return super()._compute_name()

    def _source_document_name(self):
        return self.pos_order_id.name if self.pos_order_id else super()._source_document_name()

    def _source_vat_error(self):
        return self.pos_order_id._meinvoice_vat_error() if self.pos_order_id else super()._source_vat_error()

    def action_publish(self):
        # Nháp POS nằm chờ kế toán duyệt, thường gửi CQT sau ngày bán; CQT đòi InvDate là
        # ngày gửi thực tế, để ngày bán thì bị InvalidInvoiceDate.
        self.ensure_one()
        if self.pos_order_id and self.state == 'draft':
            today_local = datetime.now(pytz.timezone(self._pos_timezone())).date()
            if self.inv_date != today_local:
                self.inv_date = today_local
        return super().action_publish()

    def _pos_timezone(self):
        return self.env.company.partner_id.tz or self.env.user.tz or 'Asia/Ho_Chi_Minh'
