from odoo import models, fields, api

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # Biến đếm số lần in
    picking_slip_print_count = fields.Integer(string='Số lần in phiếu', default=0, copy=False)

    def action_print_batch_picking_slip(self):
        """
        Hàm in hàng loạt:
        1. Tăng biến đếm.
        2. Ghi log (Ai in, lúc nào).
        3. Trả về file PDF.
        """
        # Tăng biến đếm và ghi log cho từng đơn được chọn
        for order in self:
            order.picking_slip_print_count += 1
            order.message_post(body=f"Đã in phiếu lấy hàng (Lần {order.picking_slip_print_count})")
        
        # Gọi Report in (Ở đây mình dùng Report mặc định của Sale, 
        # bạn có thể đổi 'sale.action_report_saleorder' thành ID report phiếu lấy hàng riêng của bạn)
        return self.env.ref('sale.action_report_saleorder').report_action(self)