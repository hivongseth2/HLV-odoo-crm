# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    loyalty_points_earned = fields.Integer(
        string='Điểm tích lũy', readonly=True, copy=False,
        help='Số điểm loyalty được tích cho khách hàng từ phiếu giao này',
    )

    def button_validate(self):
        """Override để tích điểm khi giao hàng / thu hồi điểm khi trả hàng."""
        res = super().button_validate()
        for picking in self:
            if picking.state == 'done':
                picking._loyalty_earn_points()
                picking._loyalty_return_points()
        return res

    def _loyalty_earn_points(self):
        """Tích điểm loyalty khi phiếu xuất kho hoàn tất giao hàng."""
        self.ensure_one()

        # Chỉ áp dụng cho phiếu xuất kho giao hàng cho khách
        if self.picking_type_code != 'outgoing':
            return
        if not self.sale_id:
            return

        sale_order = self.sale_id
        partner = sale_order.partner_id
        if not partner:
            return

        # Tìm chương trình loyalty đang active
        program = self.env['loyalty.program'].sudo().search([
            ('active', '=', True),
        ], limit=1)
        if not program:
            return

        # Tính giá trị đơn hàng (sau chiết khấu)
        order_amount = sale_order.amount_untaxed
        if order_amount <= 0:
            return

        # Tính số điểm
        points = program.calculate_points(order_amount)
        if points <= 0:
            return

        # Kiểm tra xem phiếu này đã tích điểm chưa (tránh duplicate)
        existing = self.env['loyalty.history'].sudo().search([
            ('picking_id', '=', self.id),
            ('transaction_type', '=', 'earn'),
        ], limit=1)
        if existing:
            return

        # Tạo bản ghi lịch sử điểm
        self.env['loyalty.history'].sudo().create({
            'partner_id': partner.id,
            'point_amount': points,
            'transaction_type': 'earn',
            'description': f'Tích điểm đơn hàng {sale_order.name} - Phiếu {self.name}',
            'picking_id': self.id,
            'sale_order_id': sale_order.id,
            'company_id': self.company_id.id,
            'sale_company_id': sale_order.company_id.id,
            'delivery_company_id': self.company_id.id,
        })

        self.loyalty_points_earned = points
        _logger.info(
            'Loyalty: Tích %d điểm cho %s từ phiếu %s (SO: %s)',
            points, partner.name, self.name, sale_order.name,
        )

    def _loyalty_return_points(self):
        """Thu hồi điểm khi trả hàng."""
        self.ensure_one()

        # Chỉ áp dụng cho phiếu nhập kho trả hàng từ khách
        if self.picking_type_code != 'incoming':
            return

        # Tìm phiếu xuất gốc từ origin
        origin_picking = self.env['stock.picking'].sudo().search([
            ('name', '=', self.origin),
            ('picking_type_code', '=', 'outgoing'),
            ('state', '=', 'done'),
        ], limit=1)
        if not origin_picking or not origin_picking.sale_id:
            return

        partner = origin_picking.sale_id.partner_id
        if not partner:
            return

        # Kiểm tra đã thu hồi chưa
        existing = self.env['loyalty.history'].sudo().search([
            ('picking_id', '=', self.id),
            ('transaction_type', '=', 'return'),
        ], limit=1)
        if existing:
            return

        # Tính giá trị hàng trả lại
        return_amount = sum(
            move.product_id.lst_price * move.quantity
            for move in self.move_ids
            if move.state == 'done'
        )
        if return_amount <= 0:
            return

        program = self.env['loyalty.program'].sudo().search([
            ('active', '=', True),
        ], limit=1)
        if not program:
            return

        points_to_deduct = program.calculate_points(return_amount)
        if points_to_deduct <= 0:
            return

        self.env['loyalty.history'].sudo().create({
            'partner_id': partner.id,
            'point_amount': -points_to_deduct,
            'transaction_type': 'return',
            'description': f'Thu hồi điểm do hoàn hàng phiếu {self.name}',
            'picking_id': self.id,
            'sale_order_id': origin_picking.sale_id.id,
            'company_id': self.company_id.id,
            'sale_company_id': origin_picking.sale_id.company_id.id,
            'delivery_company_id': self.company_id.id,
        })
        _logger.info(
            'Loyalty: Thu hồi %d điểm từ %s do hoàn hàng phiếu %s',
            points_to_deduct, partner.name, self.name,
        )
