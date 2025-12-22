from odoo import models

class SaleOrder(models.Model):
    _inherit = 'sale.order'
    _sql_constraints = [
        ('name_unique', 'unique(name)', 'Mã đơn hàng (Reference) đã tồn tại trong hệ thống!'),
    ]

    def action_print_label(self):
        return self.env.ref('sale_order_label.action_report_sale_order_label').report_action(self)

