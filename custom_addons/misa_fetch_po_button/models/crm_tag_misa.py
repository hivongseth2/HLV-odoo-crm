from odoo import models, fields

class CrmTag(models.Model):
    _inherit = 'crm.tag'

    misa_keywords = fields.Text(
        string="Từ Khóa",
        help="Danh sách từ khóa địa chỉ (phân cách bằng dấu phẩy) để tự động mapping khi đồng bộ MISA."
    )
    misa_ignore_htgh_patterns = fields.Text(
        string="Regex Bỏ Qua (HTGH)",
        help="Danh sách biểu thức regex (mỗi dòng 1 pattern). "
             "Nếu trường x_studio_htgh của đơn hàng khớp với bất kỳ pattern nào, "
             "tag này sẽ KHÔNG được gắn vào đơn hàng đó."
    )
