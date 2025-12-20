# models/sale_order_misa_id.py
from odoo import models, fields

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    misa_id = fields.Char(string="MISA ID", copy=False, index=True)
    x_studio_crm_elivery = fields.Boolean(
        string="Vận chuyển CRM", 
        default=False,
        copy=False,
        help="Khi tích chọn, phiếu xuất kho sẽ tự động tạo tuyến vận chuyển trên MISA CRM"
    )



class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    note = fields.Text(string="Note")