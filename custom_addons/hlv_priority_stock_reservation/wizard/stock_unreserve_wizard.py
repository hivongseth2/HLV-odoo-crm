# -*- coding: utf-8 -*-

from markupsafe import Markup
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class StockUnreserveWizard(models.TransientModel):
    _name = 'stock.unreserve.wizard'
    _description = 'Hủy dự trữ đơn hàng để nhường hàng'

    picking_id = fields.Many2one('stock.picking', string='Đơn hàng cần hàng', readonly=True)
    summary_ids = fields.One2many('stock.unreserve.wizard.summary', 'wizard_id', string='Tình trạng tồn kho')
    line_ids = fields.One2many('stock.unreserve.wizard.line', 'wizard_id', string='Danh sách các đơn đang giữ hàng')

    def action_confirm(self):
        self.ensure_one()
        selected_lines = self.line_ids.filtered(lambda l: l.unreserve_qty > 0)
        if not selected_lines:
            return

        receiver_picking = self.picking_id
        details_for_receiver = []

        for line in selected_lines:
            move = line.move_id
            victim_picking = line.picking_id
            qty_to_unreserve = line.unreserve_qty
            
            if qty_to_unreserve > line.reserved_qty:
                raise UserError(_("Số lượng hủy dự trữ không được lớn hơn số lượng đang giữ."))

            try:
                qty_fmt = "%g" % qty_to_unreserve
                # 1. Ghi log vào đơn bị rút hàng (Đơn nạn nhân)
                victim_picking.message_post(body=Markup(_(
                    "Hệ thống đã rút %s %s của sản phẩm <b>%s</b> để nhường cho đơn hàng <a href='#' data-oe-model='stock.picking' data-oe-id='%s'>%s</a>."
                )) % (qty_fmt, line.uom_id.name, move.product_id.display_name, receiver_picking.id, receiver_picking.name))
                
                # Lưu thông tin để ghi log vào đơn nhận hàng
                details_for_receiver.append(
                    Markup(_("• %s %s <b>%s</b> từ đơn hàng <a href='#' data-oe-model='stock.picking' data-oe-id='%s'>%s</a>")) 
                    % (qty_fmt, line.uom_id.name, move.product_id.display_name, victim_picking.id, victim_picking.name)
                )

                # 2. Thực hiện hủy dự trữ một phần
                self._partial_unreserve(move, qty_to_unreserve)
            except Exception:
                continue

        # 3. Ghi log tổng hợp vào đơn nhận hàng (Đơn hiện tại)
        if details_for_receiver:
            msg = Markup(_("Đã lấy hàng dự trữ từ các đơn khác:<br/>%s")) % (Markup("<br/>").join(details_for_receiver))
            receiver_picking.message_post(body=msg)

        # 4. Sau khi hủy, thực hiện dự trữ lại cho đơn hiện tại
        if receiver_picking:
            receiver_picking.with_context(skip_unreserve_wizard=True).action_assign()
            
        return {'type': 'ir.actions.act_window_close'}

    def _partial_unreserve(self, move, qty_to_unreserve):
        """
        Duyệt qua các move line để hủy dự trữ một phần.
        """
        remaining_qty = qty_to_unreserve
        # Sắp xếp move lines theo số lượng hoặc ID để ổn định
        for ml in move.move_line_ids:
            if remaining_qty <= 0:
                break
            
            res_qty = ml.quantity
            if res_qty <= 0:
                continue
            
            if res_qty <= remaining_qty:
                ml.quantity = 0
                remaining_qty -= res_qty
            else:
                ml.quantity = res_qty - remaining_qty
                remaining_qty = 0
        
        move._recompute_state()

class StockUnreserveWizardSummary(models.TransientModel):
    _name = 'stock.unreserve.wizard.summary'
    _description = 'Tóm tắt tình trạng tồn kho từng sản phẩm'

    wizard_id = fields.Many2one('stock.unreserve.wizard', string='Wizard')
    product_id = fields.Many2one('product.product', string='Sản phẩm', readonly=True)
    location_id = fields.Many2one('stock.location', string='Vị trí', readonly=True)
    demand_qty = fields.Float(string='Cần', readonly=True)
    already_reserved = fields.Float(string='Đã giữ từ kho trống', readonly=True)
    still_needed = fields.Float(string='Còn thiếu (cần rút)', readonly=True)
    uom_id = fields.Many2one('uom.uom', string='ĐVT', readonly=True)


class StockUnreserveWizardLine(models.TransientModel):
    _name = 'stock.unreserve.wizard.line'
    _description = 'Chi tiết đơn hàng giữ hàng'

    wizard_id = fields.Many2one('stock.unreserve.wizard', string='Wizard')
    picking_id = fields.Many2one('stock.picking', string='Đơn hàng đang giữ', readonly=True)
    origin = fields.Char(string='Nguồn/Đơn báo giá', readonly=True)
    move_id = fields.Many2one('stock.move', string='Dòng giữ hàng', readonly=True)
    product_id = fields.Many2one('product.product', string='Sản phẩm', readonly=True)
    reserved_qty = fields.Float(string='Số lượng đang giữ', readonly=True)
    demand_qty = fields.Float(string='Nhu cầu', readonly=True)
    unreserve_qty = fields.Float(string='Số lượng rút', default=0.0)
    uom_id = fields.Many2one('uom.uom', string='Đơn vị', readonly=True)
    deadline_date = fields.Date(string='Hạn giao hàng', readonly=True)
