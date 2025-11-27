from odoo import models, fields, api

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    # 1. Kéo ngày MISA từ đơn bán hàng sang phiếu kho để tiện lọc
    # Store=True để có thể search nhanh trong SQL
    x_misa_date = fields.Date(related='sale_id.x_studio_misa_order_date', string='Ngày MISA', store=True)

    # 2. Biến đếm số lần in
    print_count = fields.Integer(string='Lần in', default=0, copy=False)

    # 3. Hàm in hàng loạt
    def action_print_batch_delivery_slip(self):
        for picking in self:
            picking.print_count += 1
            picking.message_post(body=f"Đã in phiếu lấy hàng (Lần {picking.print_count})")
        
        # Gọi report in phiếu xuất kho mặc định của Odoo
        return self.env.ref('stock.action_report_delivery').report_action(self)