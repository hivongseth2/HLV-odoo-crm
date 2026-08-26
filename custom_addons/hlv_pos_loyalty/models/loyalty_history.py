# -*- coding: utf-8 -*-
from odoo import models, fields, api


class HlvLoyaltyHistory(models.Model):
    _inherit = 'hlv.loyalty.history'

    pos_order_id = fields.Many2one(
        'pos.order',
        string='Đơn hàng POS',
        readonly=True,
        index=True,
        help='Đơn hàng tại quầy phát sinh điểm tích lũy này',
    )
    pos_reference = fields.Char(
        string='Mã đơn POS',
        related='pos_order_id.pos_reference',
        store=True,
        readonly=True,
    )

    @api.depends('transaction_type', 'point_amount', 'partner_id', 'pos_order_id', 'sale_order_id')
    def _compute_display_name(self):
        type_labels = dict(self._fields['transaction_type'].selection)
        for rec in self:
            label = type_labels.get(rec.transaction_type, '')
            sign = '+' if rec.point_amount >= 0 else ''
            source = ''
            if rec.pos_order_id:
                ref = rec.pos_order_id.pos_reference or rec.pos_order_id.name or f"POS#{rec.pos_order_id.id}"
                source = f" (POS: {ref})"
            elif rec.sale_order_id:
                source = f" (SO: {rec.sale_order_id.name})"
            partner_name = rec.partner_id.name or ''
            rec.display_name = f"{label}: {sign}{rec.point_amount} điểm{source} - {partner_name}"
