from odoo import fields, models


class ResUsersMisaInvoiceStatus(models.Model):
    _inherit = 'res.users'

    # Cùng ý tưởng với hlv_sale_delivery_planning.x_sale_plan_mention_names: 1 field đăng ký
    # danh sách giá trị hợp lệ (ở đây là MÃ SALE MISA, khớp misa_invoice_saler_code) cho trang
    # public /misa_sale_status — KHÔNG cần user thực sự đăng nhập Odoo bằng tài khoản này, field
    # chỉ là nơi admin khai báo các mã sale hợp lệ để gộp lại thành 1 danh sách chọn trên trang
    # public (xem stock.picking.get_misa_invoice_saler_code_registry). Nhiều sale dùng chung 1
    # mật khẩu trang public thì tự chọn đúng mã của mình trong danh sách này mỗi lần vào trang.
    x_misa_saler_codes = fields.Char(
        string='Mã sale MISA (trang public /misa_sale_status)',
        help=(
            'Danh sách mã sale MISA hợp lệ hiển thị trong ô chọn trên trang public '
            '/misa_sale_status, phân tách bằng dấu phẩy. Ví dụ: NV001, NV002.'
        ),
    )
