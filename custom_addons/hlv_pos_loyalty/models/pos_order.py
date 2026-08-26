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

    loyalty_exchange_points_earned = fields.Integer(
        string='Điểm đổi thưởng POS',
        readonly=True,
        help='Điểm đổi thưởng được tính từ chiết khấu trên đơn POS này.',
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
            if (
                not order.loyalty_account_id
                or order.loyalty_points_earned > 0
                or order.loyalty_exchange_points_earned > 0
            ):
                continue

            program = self.env['hlv.loyalty.program'].sudo().search([('active', '=', True)], limit=1)
            if not program or program.earning_amount <= 0:
                continue

            # Tính điểm xếp hạng từ tổng tiền
            amount = order.amount_total
            points = int(amount / program.earning_amount) * program.earning_points
            pos_line_total = sum(
                max(line.qty or 0.0, 0.0) * max(line.price_unit or 0.0, 0.0)
                for line in order.lines
            )
            discount_amount = sum(
                max(line.qty or 0.0, 0.0)
                * max(line.price_unit or 0.0, 0.0)
                * min(max(line.discount or 0.0, 0.0), 100.0)
                / 100.0
                for line in order.lines
            )
            discount_source = 'POS line discounts'
            if discount_amount <= 0:
                # Keep POS aligned with the Sale/Picking flow: when no line
                # discount is recorded, use the member's configured default
                # Loyalty discount as the exchange-point basis.
                loyalty_partner = order.loyalty_account_id.partner_id
                root_partner = (
                    loyalty_partner._get_loyalty_root() if loyalty_partner else False
                )
                fallback_discount = (
                    root_partner.loyalty_default_discount if root_partner else 0.0
                ) or 0.0
                if fallback_discount > 0:
                    discount_amount = pos_line_total * fallback_discount
                    discount_source = (
                        f'Member default Loyalty discount ({fallback_discount:.2%})'
                    )
            exchange_points = (
                int(discount_amount / program.discount_per_point)
                if discount_amount > 0 and program.discount_per_point > 0
                else 0
            )
            if points <= 0 and exchange_points <= 0:
                continue

            order_ref = order.pos_reference or order.name or f"POS#{order.id}"
            company_name = order.company_id.name or ''
            desc = f"Tích điểm mua sắm tại cửa hàng - Đơn hàng {order_ref} ({amount:,.0f}đ)"
            formula = f"Tổng tiền đơn hàng: {amount:,.0f} VNĐ / {program.earning_amount:,.0f} VNĐ = {points} điểm xếp hạng ({company_name})"

            ranking_history = self.env['hlv.loyalty.history'].sudo().create({
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
            if points > 0:
                order.loyalty_points_earned = points
            else:
                # The order can earn exchange points without reaching a
                # ranking-point threshold; do not retain a zero-point record.
                ranking_history.unlink()

            if exchange_points > 0:
                self.env['hlv.loyalty.history'].sudo().create({
                    'partner_id': order.partner_id.id,
                    'account_id': order.loyalty_account_id.id,
                    'pos_order_id': order.id,
                    'point_amount': exchange_points,
                    'point_type': 'exchange',
                    'transaction_type': 'earn',
                    # Exchange points stay out of the usable balance until a
                    # staff member confirms the record.
                    'state': 'pending',
                    'description': f'POS exchange points - Order {order_ref}',
                    'point_formula': (
                        f'{discount_source}: {discount_amount:,.0f} VND / '
                        f'{program.discount_per_point:,.0f} VND = '
                        f'{exchange_points} exchange points ({company_name})'
                    ),
                    'company_id': order.company_id.id,
                    'date': order.date_order or fields.Datetime.now(),
                })
                order.loyalty_exchange_points_earned = exchange_points
