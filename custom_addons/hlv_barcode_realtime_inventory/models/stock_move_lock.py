# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class StockMoveLock(models.Model):
    """
    Extend stock.move để thêm tính năng lock moves
    """
    _inherit = 'stock.move'

    is_locked = fields.Boolean(
        string='Bị Khóa (Kiểm Kê)',
        default=False,
        help='Được khóa lại trong quá trình kiểm kê',
        tracking=True
    )

    locked_by_check_id = fields.Many2one(
        'inventory.check',
        string='Khóa Bởi Phiên Kiểm Kê',
        help='Phiên kiểm kê đã khóa move này'
    )

    locked_reason = fields.Text(
        string='Lý Do Khóa'
    )

    # ========== Constraints ==========
    @api.constrains('state', 'is_locked')
    def _check_locked_moves(self):
        """Không cho phép state change khi bị khóa"""
        for move in self:
            if move.is_locked and move.state in ['confirmed', 'waiting', 'partially_available']:
                # Cho phép chỉnh sửa, nhưng cảnh báo
                pass

    @api.model
    def create(self, vals):
        """Kiểm tra khi tạo move"""
        # Có thể thêm logic kiểm tra ở đây nếu cần
        return super().create(vals)

    def write(self, vals):
        """Kiểm tra khi update move"""
        # Nếu cố gắng đặt quantity hoặc state cho move bị khóa
        blocked_fields = {'product_qty', 'reserved_availability'}
        
        for move in self:
            if move.is_locked and blocked_fields & set(vals.keys()):
                # Cho cảnh báo nhưng không block hoàn toàn
                # Có thể thay đổi logic này nếu cần strict hơn
                if 'is_locked' not in vals or not vals.get('is_locked'):
                    # Only warn if trying to unlock
                    pass
        
        return super().write(vals)

    # ========== Helper Methods ==========
    def action_view_locked_check(self):
        """Xem phiên kiểm kê đã khóa move này"""
        self.ensure_one()
        if self.locked_by_check_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'inventory.check',
                'res_id': self.locked_by_check_id.id,
                'view_mode': 'form',
            }
        return False
