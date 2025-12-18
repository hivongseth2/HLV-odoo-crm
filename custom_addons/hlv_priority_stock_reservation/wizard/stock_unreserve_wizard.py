# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError

class StockUnreserveWizard(models.TransientModel):
    _name = 'stock.unreserve.wizard'
    _description = 'Hủy dự trữ đơn hàng để nhường hàng'

    picking_id = fields.Many2one('stock.picking', string='Đơn hàng cần hàng', readonly=True)
    line_ids = fields.One2many('stock.unreserve.wizard.line', 'wizard_id', string='Danh sách các đơn đang giữ hàng')

    def action_confirm(self):
        self.ensure_one()
        selected_lines = self.line_ids.filtered(lambda l: l.unreserve_qty > 0)
        if not selected_lines:
            return

        picking_to_reassign = self.picking_id

        for line in selected_lines:
            move = line.move_id
            qty_to_unreserve = line.unreserve_qty
            
            if qty_to_unreserve > line.reserved_qty:
                raise UserError(_("Số lượng hủy dự trữ không được lớn hơn số lượng đang giữ."))

            try:
                # Ghi log vào đơn bị hủy
                move.picking_id.message_post(body=_(
                    "Người dùng đã thủ công hủy dự trữ %s %s của sản phẩm '%s' để nhường cho đơn hàng %s."
                ) % (qty_to_unreserve, line.uom_id.name, move.product_id.display_name, picking_to_reassign.name))
                
                # Thực hiện hủy dự trữ một phần (hoặc toàn bộ)
                # Odoo 17/18: _do_unreserve() không hỗ trợ số lượng, ta phải can thiệp vào move lines
                self._partial_unreserve(move, qty_to_unreserve)
            except Exception as e:
                continue

        # Sau khi hủy, thực hiện dự trữ lại cho đơn hiện tại
        if picking_to_reassign:
            # bypass wizard khi gọi lại action_assign để tránh vòng lặp
            picking_to_reassign.with_context(skip_unreserve_wizard=True).action_assign()
            
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def _partial_unreserve(self, move, qty_to_unreserve):
        """
        Duyệt qua các move line để hủy dự trữ một phần.
        """
        remaining_qty = qty_to_unreserve
        for ml in move.move_line_ids:
            if remaining_qty <= 0:
                break
            
            res_qty = ml.quantity
            if res_qty <= 0:
                continue
            
            if res_qty <= remaining_qty:
                # Nếu line này ít hơn hoặc bằng số cần hủy -> xóa hoặc set qty = 0
                ml.quantity = 0
                remaining_qty -= res_qty
            else:
                # Nếu line này nhiều hơn số cần hủy -> trừ bớt
                ml.quantity = res_qty - remaining_qty
                remaining_qty = 0
        
        # Cập nhật lại trạng thái của move nếu cần
        move._recompute_state()

class StockUnreserveWizardLine(models.TransientModel):
    _name = 'stock.unreserve.wizard.line'
    _description = 'Chi tiết đơn hàng giữ hàng'

    wizard_id = fields.Many2one('stock.unreserve.wizard', string='Wizard')
    picking_id = fields.Many2one('stock.picking', string='Đơn hàng đang giữ', readonly=True)
    move_id = fields.Many2one('stock.move', string='Dòng giữ hàng', readonly=True)
    product_id = fields.Many2one('product.product', string='Sản phẩm', readonly=True)
    reserved_qty = fields.Float(string='Số lượng đang giữ', readonly=True)
    unreserve_qty = fields.Float(string='SL muốn lấy', default=0.0)
    uom_id = fields.Many2one('uom.uom', string='Đơn vị', readonly=True)
    deadline_date = fields.Date(string='Hạn giao hàng', readonly=True)
