from odoo import models, fields

class CrmTag(models.Model):
    _inherit = 'crm.tag'

    misa_keywords = fields.Text(
        string="MISA Keywords",
        help="Danh sách từ khóa địa chỉ (phân cách bằng dấu phẩy) để tự động mapping khi đồng bộ MISA."
    )
