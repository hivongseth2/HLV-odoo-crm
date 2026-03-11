# -*- coding: utf-8 -*-
from odoo import models, fields, api


class InventoryCheckLine(models.Model):
    """
    Chi tiết từng sản phẩm/lot/package trong một phiên kiểm kê
    """
    _name = 'inventory.check.line'
    _description = 'Dòng Kiểm Kê - Chi Tiết Sản Phẩm'
    _order = 'create_date desc'

    # ========== Relationships ==========
    check_id = fields.Many2one(
        'inventory.check',
        string='Phiên Kiểm Kê',
        required=True,
        ondelete='cascade',
        index=True
    )

    product_id = fields.Many2one(
        'product.product',
        string='Sản Phẩm',
        required=True,
        index=True
    )

    location_id = fields.Many2one(
        'stock.location',
        string='Vị Trí',
        required=True,
        index=True
    )

    lot_id = fields.Many2one(
        'stock.lot',
        string='Lot/Serial'
    )

    package_id = fields.Many2one(
        'stock.quant.package',
        string='Kiện'
    )

    # ========== Quantities ==========
    scanned_qty = fields.Float(
        string='Số Lượng Thực Tế',
        default=0.0,
        required=True,
        help='Số lượng đã quét/đếm được'
    )

    theoretical_qty = fields.Float(
        string='Số Lượng Lý Thuyết',
        default=0.0,
        help='Số lượng trong hệ thống tại thời điểm bắt đầu'
    )

    difference = fields.Float(
        string='Chênh Lệch',
        compute='_compute_difference',
        store=True,
        help='Chênh lệch = Thực tế - Lý thuyết'
    )

    # ========== Discrepancy Link ==========
    discrepancy_id = fields.Many2one(
        'inventory.discrepancy',
        string='Ghi Nhận Chênh Lệch',
        help='Link đến ghi nhận chênh lệch'
    )

    # ========== Audit Trail ==========
    scanned_by = fields.Many2one(
        'res.users',
        string='Quét Bởi',
        related='check_id.user_id',
        store=True
    )

    scanned_at = fields.Datetime(
        string='Quét Lúc',
        default=fields.Datetime.now
    )

    updated_at = fields.Datetime(
        string='Cập Nhật Lúc',
        auto_now=True
    )

    # ========== Compute & Constraints ==========
    @api.depends('scanned_qty', 'theoretical_qty')
    def _compute_difference(self):
        """Tính toán chênh lệch"""
        for line in self:
            line.difference = line.scanned_qty - line.theoretical_qty

    @api.constrains('product_id', 'location_id')
    def _check_product_location(self):
        """Constraint: không trùng product + location"""
        for line in self:
            # Kiểm tra xem có line khác cùng product, location, lot, package không
            duplicate = self.search([
                ('check_id', '=', line.check_id.id),
                ('product_id', '=', line.product_id.id),
                ('location_id', '=', line.location_id.id),
                ('lot_id', '=', line.lot_id.id),
                ('package_id', '=', line.package_id.id),
                ('id', '!=', line.id),
            ])
            
            if duplicate:
                from odoo.exceptions import ValidationError
                raise ValidationError(
                    f'Sản phẩm {line.product_id.name} đã có trong kiểm kê này'
                )

    # ========== Helper Methods ==========
    def get_line_data(self):
        """Trả về dữ liệu line cho frontend"""
        self.ensure_one()
        return {
            'id': self.id,
            'product_id': self.product_id.id,
            'product_code': self.product_id.default_code or '',
            'product_name': self.product_id.display_name,
            'product_barcode': self.product_id.barcode or '',
            'uom_name': self.product_id.uom_id.name or 'Cái',
            'scanned_qty': self.scanned_qty,
            'theoretical_qty': self.theoretical_qty,
            'difference': self.difference,
            'location_id': self.location_id.id,
            'location_name': self.location_id.display_name,
            'lot_id': self.lot_id.id if self.lot_id else False,
            'lot_name': self.lot_id.name if self.lot_id else '',
            'package_id': self.package_id.id if self.package_id else False,
            'package_name': self.package_id.name if self.package_id else '',
        }

    def action_open_discrepancy(self):
        """Mở form ghi nhận chênh lệch"""
        self.ensure_one()
        
        if self.difference == 0:
            from odoo.exceptions import UserError
            raise UserError('Không có chênh lệch để ghi nhận')
        
        # Nếu chưa có discrepancy, tạo mới
        if not self.discrepancy_id:
            discrepancy = self.env['inventory.discrepancy'].create({
                'check_id': self.check_id.id,
                'line_id': self.id,
                'product_id': self.product_id.id,
                'difference': self.difference,
            })
            self.discrepancy_id = discrepancy.id
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'inventory.discrepancy',
            'res_id': self.discrepancy_id.id,
            'view_mode': 'form',
            'target': 'new',
        }
