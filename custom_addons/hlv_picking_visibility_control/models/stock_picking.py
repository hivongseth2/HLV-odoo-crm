# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.osv import expression


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    is_hidden_picking = fields.Boolean(
        string='Ẩn khỏi menu',
        compute='_compute_is_hidden_picking',
        store=True,
        help='Phiếu này sẽ bị ẩn khỏi danh sách chính'
    )
    allow_menu_access = fields.Boolean(
        string='Cho phép truy cập Menu',
        default=False,
        help='Nếu check, phiếu này có thể được xem trực tiếp từ menu'
    )

    @api.depends('picking_type_id', 'picking_type_id.is_hidden_from_menu')
    def _compute_is_hidden_picking(self):
        """Tính toán xem phiếu này có nên bị ẩn không"""
        for picking in self:
            picking.is_hidden_picking = (
                picking.picking_type_id.is_hidden_from_menu 
                and not picking.allow_menu_access
            )

    @api.model
    def _get_domain_for_list_view(self):
        """
        Trả về domain để lọc các phiếu sẽ hiển thị trong list view
        Ẩn các phiếu có loại là phiếu bàn giao (BBGN, BBBG, v.v.)
        """
        return [
            '|',
            ('picking_type_id.is_hidden_from_menu', '=', False),
            ('allow_menu_access', '=', True),
        ]

    @api.model
    def search(self, args, offset=0, limit=None, order=None, count=False):
        """
        Override search để tự động thêm domain ẩn phiếu
        """
        # Kiểm tra xem chúng ta có đang trong context của list view không
        if not self.env.context.get('show_all_pickings'):
            domain_hidden = self._get_domain_for_list_view()
            args = expression.AND([args, domain_hidden])
        
        return super().search(args, offset=offset, limit=limit, order=order, count=count)

    def action_open_hidden_picking(self):
        """
        Action để mở các phiếu bị ẩn (dùng từ phiếu xuất kho chính)
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
            'context': self.env.context,
        }

    def button_print_delivery_note(self):
        """
        In phiếu bàn giao từ phiếu xuất kho
        """
        self.ensure_one()
        # Tìm các phiếu bàn giao liên quan (từ picking này)
        related_pickings = self.env['stock.picking'].search([
            ('origin', '=', self.name),
            ('picking_type_id.is_delivery_note_type', '=', True),
        ])
        
        if not related_pickings:
            return self._action_print_picking()
        
        # In phiếu bàn giao liên quan
        return related_pickings._action_print_picking()

    def _action_print_picking(self):
        """In phiếu"""
        return self.env.ref('stock.action_report_picking').report_action(self)
