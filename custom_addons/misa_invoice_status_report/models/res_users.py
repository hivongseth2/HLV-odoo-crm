from odoo import fields, models


class ResUsersMisaInvoiceStatus(models.Model):
    _inherit = 'res.users'

    # Danh sách mã sale MISA (khớp misa_invoice_saler_code) mà CHÍNH tài khoản này được xem khi
    # đăng nhập vào trang /misa_sale_status (route auth='user', dùng thẳng session Odoo thật —
    # KHÔNG còn 1 mật khẩu chung cho mọi sale như trước). 1 tài khoản có thể được gán nhiều mã
    # (VD trưởng nhóm quản lý nhiều sale) — xem stock.picking.get_misa_invoice_saler_code_registry
    # (chỉ đọc field này của self.env.user, không gộp của user khác).
    x_misa_saler_codes = fields.Char(
        string='Mã sale MISA (trang /misa_sale_status)',
        help=(
            'Danh sách mã sale MISA mà TÀI KHOẢN NÀY được xem khi đăng nhập vào trang '
            '/misa_sale_status, phân tách bằng dấu phẩy. Ví dụ: NV001, NV002. Tài khoản khác '
            'sẽ KHÔNG thấy được các mã này.'
        ),
    )
