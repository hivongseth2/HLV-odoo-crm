# -*- coding: utf-8 -*-

from odoo import models, fields, api, _

class StockUnreserveWizard(models.TransientModel):
    _name = 'stock.unreserve.wizard'
    _description = 'Hủy dự trữ đơn hàng để nhường hàng'

    picking_id = fields.Many2one('stock.picking', string='Đơn hàng cần hàng', readonly=True)
    line_ids = fields.One2many('stock.unreserve.wizard.line', 'wizard_id', string='Danh sách các đơn đang giữ hàng')

    def action_confirm(self):
        self.ensure_one()
        selected_lines = self.line_ids.filtered(lambda l: l.is_selected)
        if not selected_lines:
            return

        # Nhóm theo move_id của nạn nhân
        victim_moves = selected_lines.mapped('move_id')
        picking_to_reassign = self.picking_id

        for move in victim_moves:
            try:
                # Ghi log vào đơn bị hủy
                move.picking_id.message_post(body=_(
                    "Người dùng đã thủ công hủy dự trữ sản phẩm '%s' để nhường cho đơn hàng %s."
                ) % (move.product_id.display_name, picking_to_reassign.name))
                
                # Thực hiện hủy dự trữ
                move._do_unreserve()
            except Exception:
                continue

        # Sau khi hủy, thực hiện dự trữ lại cho đơn hiện tại
        if picking_to_reassign:
            picking_to_reassign.action_assign()
            
        return {'type': 'ir.actions.client', 'tag': 'reload'}

class StockUnreserveWizardLine(models.TransientModel):
    _name = 'stock.unreserve.wizard.line'
    _description = 'Chi tiết đơn hàng giữ hàng'

    wizard_id = fields.Many2one('stock.unreserve.wizard', string='Wizard')
    is_selected = fields.Boolean(string='Chọn', default=True)
    picking_id = fields.Many2one('stock.picking', string='Đơn hàng đang giữ', readonly=True)
    move_id = fields.Many2one('stock.move', string='Dòng giữ hàng', readonly=True)
    product_id = fields.Many2one('product.product', string='Sản phẩm', readonly=True)
    reserved_qty = fields.Float(string='Số lượng đang giữ', readonly=True)
    uom_id = fields.Many2one('uom.uom', string='Đơn vị', readonly=True)
    deadline_date = fields.Date(string='Hạn giao hàng', readonly=True)
