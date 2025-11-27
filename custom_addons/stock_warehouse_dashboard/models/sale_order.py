from odoo import models, fields, api

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    picking_slip_print_count = fields.Integer(string='Số lần in phiếu', default=0, copy=False)

    def action_print_batch_picking_slip(self):
        # Tăng biến đếm và ghi log
        for order in self:
            order.picking_slip_print_count += 1
            order.message_post(body=f"Đã in phiếu lấy hàng (Lần {order.picking_slip_print_count})")
        
        # In phiếu (Sử dụng report mặc định của Sale Order)
        # Nếu bạn có report riêng, thay 'sale.action_report_saleorder' bằng ID report đó
        return self.env.ref('sale.action_report_saleorder').report_action(self)