from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    x_is_shared_driver = fields.Boolean(
        string='Tài khoản tài xế dùng chung',
        help='Bật cho tài khoản kiểu "Tài xế khác" mà nhiều tài xế thuê ngoài cùng dùng. '
             'Khi bật, chuyến bắt buộc phải ghi tên tài xế thật.',
    )
    dispatch_driver_name = fields.Char(
        string='Tên tài xế hiển thị', compute='_compute_dispatch_driver_name',
    )

    @api.depends('name')
    def _compute_dispatch_driver_name(self):
        """Tên tài xế luôn lấy từ shipper_name của module hlv_barcode_shipper.

        Dùng getattr vì module này không depend cứng hlv_barcode_shipper — nhưng khi
        module đó có mặt (thực tế đang chạy) thì shipper_name là tên duy nhất người
        trong kho nhận ra.
        """
        for user in self:
            user.dispatch_driver_name = (
                getattr(user, 'shipper_name', '') or ''
            ).strip() or user.name
