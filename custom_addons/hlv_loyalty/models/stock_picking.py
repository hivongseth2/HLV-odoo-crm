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

        # Tính tổng tiền chiết khấu trên các dòng hàng
        discount_amount = sum(
            line.price_unit * line.product_uom_qty * line.discount / 100.0
            for line in sale_order.order_line
            if line.discount > 0 and not line.display_type
        )

        # Fallback: nếu không có dòng nào chiết khấu → dùng % mặc định của contact
        if discount_amount <= 0:
            root_partner_lookup = partner.commercial_partner_id or partner
            fallback_pct = root_partner_lookup.loyalty_default_discount or 0.0
            discount_amount = sale_order.amount_untaxed * fallback_pct / 100.0

        if discount_amount <= 0:
            return

        # Tính số điểm
        points = program.calculate_points(discount_amount)
        if points <= 0:
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
            'point_amount': points,
            'transaction_type': 'earn',
            'description': f'Tích điểm đơn hàng {sale_order.name} - Phiếu {self.name}',
            'picking_id': self.id,
            'sale_order_id': sale_order.id,
            'company_id': self.company_id.id,
            'sale_company_id': sale_order.company_id.id,
            'delivery_company_id': self.company_id.id,
        }

        # 1. Điểm xếp hạng – tự động xác nhận
        self.env['hlv.loyalty.history'].sudo().create({
            **base_vals,
            'point_type': 'ranking',
            'state': 'confirmed',
        })

        # 2. Điểm đổi thưởng – chờ nhân viên xác nhận
        self.env['hlv.loyalty.history'].sudo().create({
            **base_vals,
            'point_type': 'exchange',
            'state': 'pending',
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
        existing = self.env['hlv.loyalty.history'].sudo().search([
            ('picking_id', '=', self.id),
            ('transaction_type', '=', 'return'),
        ], limit=1)
        if existing:
            return

        # Thu hồi đúng số điểm đã tích ở phiếu xuất gốc
        points_to_deduct = origin_picking.loyalty_points_earned
        if points_to_deduct <= 0:
            return

        # Luôn thu hồi từ công ty gốc
        root_partner = partner.commercial_partner_id or partner

        base_vals = {
            'partner_id': root_partner.id,
            'point_amount': -points_to_deduct,
            'transaction_type': 'return',
            'description': f'Thu hồi điểm do hoàn hàng phiếu {self.name}',
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
        self.env['hlv.loyalty.history'].sudo().create({
            **base_vals,
            'point_type': 'ranking',
            'state': 'confirmed',
        })

        # Thu hồi điểm đổi thưởng đã xác nhận (nếu có)
        confirmed_exchange = self.env['hlv.loyalty.history'].sudo().search([
            ('picking_id', '=', origin_picking.id),
            ('point_type', '=', 'exchange'),
            ('state', '=', 'confirmed'),
        ])
        if confirmed_exchange:
            self.env['hlv.loyalty.history'].sudo().create({
                **base_vals,
                'point_type': 'exchange',
                'state': 'confirmed',
            })
        _logger.info(
            'Loyalty: Thu hồi %d điểm từ %s do hoàn hàng phiếu %s',
            points_to_deduct, partner.name, self.name,
        )
