from odoo import models, fields, api

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # Biến đếm số lần in
    picking_slip_print_count = fields.Integer(string='Lần in', default=0, copy=False)

    def action_print_batch_picking_slip(self):
        """
        Hàm in phiếu hàng loạt cho Sale Order
        """
        for order in self:
            order.picking_slip_print_count += 1
            # Ghi log vào chatter để biết ai in
            order.message_post(body=f"Đã in phiếu (Lần {order.picking_slip_print_count})")
        
        # Gọi report in. 
        # Nếu bạn muốn in Phiếu kho (Delivery Slip) từ đơn hàng, ta sẽ gọi report của stock.picking liên quan
        # Dưới đây là in đơn hàng. Nếu muốn in phiếu kho, báo mình sửa lại đoạn này chút xíu.
        return self.env.ref('sale.action_report_saleorder').report_action(self)