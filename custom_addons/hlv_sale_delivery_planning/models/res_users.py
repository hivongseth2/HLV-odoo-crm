from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    x_packer_name = fields.Char(
        string='Tên người đóng',
        help='Tên hiển thị khi assign và đánh giá KPI đóng gói.',
    )

    x_sale_plan_mention_names = fields.Char(
        string='Sale Plan mention aliases',
        help='Danh sach alias nhan thong bao tren trang /sale_plan, phan tach bang dau phay. Vi du: thanhnhan, thanhluan.',
    )

    # Dùng cho filter "Đơn của tôi" trên trang /sale_plan (xem sale_plan_controller.py và
    # services/delivery_planner_domain.py). Đơn không có x_studio_misa_saler_code (VD: đơn
    # Shopee, đơn nhập tay) không match được theo mã sale MISA (res.users.x_misa_saler_codes,
    # field của module misa_invoice_status_report) — bật cờ này để tài khoản đó thấy TẤT CẢ đơn
    # thuộc dạng này, thay vì phải gán từng đơn lẻ.
    x_handle_unassigned_saler_orders = fields.Boolean(
        string='Xử lý đơn không có mã sale MISA (VD: Shopee)',
        help=(
            'Khi bật, filter "Đơn của tôi" trên trang /sale_plan sẽ hiển thị thêm TẤT CẢ đơn '
            'không có mã sale MISA (VD: đơn Shopee) cho tài khoản này, ngoài các đơn khớp mã '
            'sale MISA đã khai báo ở "Mã sale MISA".'
        ),
    )
