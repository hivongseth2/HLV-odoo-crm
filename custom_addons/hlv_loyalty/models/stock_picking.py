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
        program = self.env['hlv.loyalty.program'].sudo().search([
            ('active', '=', True),
        ], limit=1)
        if not program:
            return

        # Tính tổng tiền hàng thực giao trong phiếu này (cho điểm xếp hạng)
        delivered_subtotal = sum(
            (move.sale_line_id.price_unit if move.sale_line_id
             else move.product_id.lst_price) * move.quantity
            for move in self.move_ids
            if move.state == 'done'
        )

        # ── Điểm xếp hạng: mỗi earning_amount tiền hàng = earning_points điểm ──
        ranking_points = 0
        if delivered_subtotal > 0 and program.earning_amount > 0:
            ranking_points = int(delivered_subtotal / program.earning_amount) * program.earning_points

        # ── Điểm đổi thưởng: dựa trên tiền chiết khấu ──
        discount_amount = sum(
            move.sale_line_id.price_unit * move.quantity
            * (move.sale_line_id.loyalty_discount_pct / 100.0)
            for move in self.move_ids
            if move.state == 'done'
            and move.sale_line_id
            and move.sale_line_id.loyalty_discount_pct > 0
        )
        # Fallback: không có dòng nào đặt loyalty_discount_pct → dùng % mặc định của contact
        if discount_amount <= 0:
            root_partner_lookup = partner.commercial_partner_id or partner
            # loyalty_default_discount lưu dạng 0-1 (Odoo convention: 0.05 = 5%)
            fallback_pct = root_partner_lookup.loyalty_default_discount or 0.0
            discount_amount = delivered_subtotal * fallback_pct

        exchange_points = 0
        if discount_amount > 0 and program.discount_per_point > 0:
            exchange_points = int(discount_amount / program.discount_per_point)

        if ranking_points <= 0 and exchange_points <= 0:
            return

        # Kiểm tra xem phiếu này đã tích điểm chưa (tránh duplicate)
        existing = self.env['hlv.loyalty.history'].sudo().search([
            ('picking_id', '=', self.id),
            ('transaction_type', '=', 'earn'),
        ], limit=1)
        if existing:
            return

        # Luôn tích vào công ty gốc (commercial_partner_id)
        root_partner = partner.commercial_partner_id or partner

        base_vals = {
            'partner_id': root_partner.id,
            'transaction_type': 'earn',
            'picking_id': self.id,
            'sale_order_id': sale_order.id,
            'company_id': self.company_id.id,
            'sale_company_id': sale_order.company_id.id,
            'delivery_company_id': self.company_id.id,
        }

        # 1. Điểm xếp hạng – tự động xác nhận
        if ranking_points > 0:
            self.env['hlv.loyalty.history'].sudo().create({
                **base_vals,
                'point_amount': ranking_points,
                'point_type': 'ranking',
                'state': 'confirmed',
                'description': f'Tích điểm xếp hạng {sale_order.name} - Phiếu {self.name}',
            })

        # 2. Điểm đổi thưởng – chờ nhân viên xác nhận
        if exchange_points > 0:
            self.env['hlv.loyalty.history'].sudo().create({
                **base_vals,
                'point_amount': exchange_points,
                'point_type': 'exchange',
                'state': 'pending',
                'description': f'Tích điểm đổi thưởng {sale_order.name} - Phiếu {self.name}',
            })

        self.loyalty_points_earned = ranking_points

        self.loyalty_points_earned = ranking_points
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
        existing = self.env['hlv.loyalty.history'].sudo().search([
            ('picking_id', '=', self.id),
            ('transaction_type', '=', 'return'),
        ], limit=1)
        if existing:
            return

        # Thu hồi đúng số điểm đã tích ở phiếu xuất gốc
        # loyalty_points_earned lưu ranking points
        ranking_to_deduct = origin_picking.loyalty_points_earned

        # Lấy số exchange points đã tích (confirmed hoặc pending) từ phiếu gốc
        origin_exchange = self.env['hlv.loyalty.history'].sudo().search([
            ('picking_id', '=', origin_picking.id),
            ('point_type', '=', 'exchange'),
            ('transaction_type', '=', 'earn'),
            ('state', 'in', ['pending', 'confirmed']),
        ], limit=1)
        exchange_to_deduct = origin_exchange.point_amount if origin_exchange else 0

        if ranking_to_deduct <= 0 and exchange_to_deduct <= 0:
            return

        # Luôn thu hồi từ công ty gốc
        root_partner = partner.commercial_partner_id or partner

        base_vals = {
            'partner_id': root_partner.id,
            'transaction_type': 'return',
            'picking_id': self.id,
            'sale_order_id': origin_picking.sale_id.id,
            'company_id': self.company_id.id,
            'sale_company_id': origin_picking.sale_id.company_id.id,
            'delivery_company_id': self.company_id.id,
        }

        # Hủy điểm exchange đang pending của phiếu gốc (chưa xác nhận)
        pending_exchange = self.env['hlv.loyalty.history'].sudo().search([
            ('picking_id', '=', origin_picking.id),
            ('point_type', '=', 'exchange'),
            ('state', '=', 'pending'),
        ])
        pending_exchange.write({'state': 'cancelled'})

        # Thu hồi điểm xếp hạng (confirmed)
        if ranking_to_deduct > 0:
            self.env['hlv.loyalty.history'].sudo().create({
                **base_vals,
                'point_amount': -ranking_to_deduct,
                'point_type': 'ranking',
                'state': 'confirmed',
                'description': f'Thu hồi điểm xếp hạng do hoàn hàng phiếu {self.name}',
            })

        # Thu hồi điểm đổi thưởng đã xác nhận (nếu có)
        confirmed_exchange = self.env['hlv.loyalty.history'].sudo().search([
            ('picking_id', '=', origin_picking.id),
            ('point_type', '=', 'exchange'),
            ('state', '=', 'confirmed'),
        ])
        if confirmed_exchange and exchange_to_deduct > 0:
            self.env['hlv.loyalty.history'].sudo().create({
                **base_vals,
                'point_amount': -exchange_to_deduct,
                'point_type': 'exchange',
                'state': 'confirmed',
                'description': f'Thu hồi điểm đổi thưởng do hoàn hàng phiếu {self.name}',
            })
        _logger.info(
            'Loyalty: Thu hồi ranking=%d exchange=%d từ %s do hoàn hàng phiếu %s',
            ranking_to_deduct, exchange_to_deduct, partner.name, self.name,
        )
