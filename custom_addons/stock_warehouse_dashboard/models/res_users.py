from odoo import models, fields

class ResUsers(models.Model):
    _inherit = 'res.users'

    allowed_warehouse_ids = fields.Many2many(
        'stock.warehouse', 
        'res_users_warehouse_rel', 
        'user_id', 'warehouse_id', 
        string='Allowed Warehouses',
        help="Chọn các kho mà user này được phép nhìn thấy trên Dashboard."
    )