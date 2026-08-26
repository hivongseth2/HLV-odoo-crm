# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    loyalty_account_id = fields.Many2one(
        'hlv.loyalty.portal.account',
        string='Tài khoản Loyalty (Portal)',
        readonly=True,
        index=True,
        help='Tài khoản cá nhân nhận điểm thưởng từ đơn POS này',
    )
    loyalty_phone = fields.Char(
        string='SĐT Loyalty',
        related='loyalty_account_id.portal_phone',
        store=True,
        readonly=True,
    )
    loyalty_points_earned = fields.Integer(
        string='Điểm tích lũy POS',
        readonly=True,
        help='Số điểm xếp hạng được tích từ đơn POS này',
    )

    @api.model
    def _order_fields(self, ui_order):
        fields_dict = super()._order_fields(ui_order)
        fields_dict['loyalty_account_id'] = ui_order.get('loyalty_account_id')
        return fields_dict

    def _process_saved_order(self, draft):
        """Hook sau khi lưu đơn POS để tính điểm tự động."""
        order_id = super()._process_saved_order(draft)
        order = self.browse(order_id)
        if order and order.state in ('paid', 'done', 'invoiced') and order.loyalty_account_id:
            order._create_loyalty_point_history()
        return order_id

    def _create_loyalty_point_history(self):
        """Tạo bản ghi lịch sử tích điểm kèm lý do và mã đơn hàng cụ thể."""
        for order in self:
            if not order.loyalty_account_id or order.loyalty_points_earned > 0:
                continue

            program = self.env['hlv.loyalty.program'].sudo().search([('active', '=', True)], limit=1)
            if not program or program.earning_amount <= 0:
                continue

            # Tính điểm xếp hạng từ tổng tiền
            amount = order.amount_total
            points = int(amount / program.earning_amount) * program.earning_points
            if points <= 0:
                continue

            order_ref = order.pos_reference or order.name or f"POS#{order.id}"
            company_name = order.company_id.name or ''
            desc = f"Tích điểm mua sắm tại cửa hàng - Đơn hàng {order_ref} ({amount:,.0f}đ)"
            formula = f"Tổng tiền đơn hàng: {amount:,.0f} VNĐ / {program.earning_amount:,.0f} VNĐ = {points} điểm xếp hạng ({company_name})"

            self.env['hlv.loyalty.history'].sudo().create({
                'partner_id': order.partner_id.id,
                'account_id': order.loyalty_account_id.id,
                'pos_order_id': order.id,
                'point_amount': points,
                'point_type': 'ranking',
                'transaction_type': 'earn',
                'state': 'confirmed',
                'description': desc,
                'point_formula': formula,
                'company_id': order.company_id.id,
                'date': order.date_order or fields.Datetime.now(),
            })
            order.loyalty_points_earned = points
