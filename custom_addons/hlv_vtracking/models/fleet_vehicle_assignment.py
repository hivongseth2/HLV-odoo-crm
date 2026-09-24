"""Ai lái xe này, và xe này thường xuất phát từ đâu.

Tách khỏi ``fleet_vehicle_capacity.py`` (xe chở được gì) và ``fleet_vehicle.py`` (định vị):
ba chuyện thay đổi vì ba lý do khác nhau.

**Tài xế nhận diện bằng TÀI KHOẢN, hiển thị bằng ``shipper_name``.** ``driver_id`` của Đội
xe trỏ tới một *đối tác*, trong khi tài xế thật đăng nhập app quét barcode bằng *tài khoản*
— và mọi số thực tế (ai nhận hàng lúc nào, ai chở về) đều ghi theo tài khoản đó. Không nối
được hai bên thì không bao giờ biết kế hoạch giao cho ai mà thực tế ai chạy.
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class FleetVehicleAssignment(models.Model):
    _inherit = 'fleet.vehicle'

    dispatch_driver_user_id = fields.Many2one(
        'res.users', string='Tài xế (tài khoản quét barcode)', index=True,
        help='Tài khoản tài xế dùng để quét nhận hàng trong app shipper. Kế hoạch của xe này '
             'mặc định giao cho người này, và số thực tế được đối chiếu theo tài khoản này.',
    )
    dispatch_driver_name = fields.Char(
        related='dispatch_driver_user_id.shipper_name', string='Tên shipper', readonly=True,
    )
    dispatch_start_place_id = fields.Many2one(
        'hlv.vtracking.place', string='Điểm xuất phát mặc định',
        domain="[('has_coords', '=', True), ('warehouse_id', '!=', False)]",
        help='Kế hoạch của xe này tạo ra mà không chỉ định điểm xuất phát thì lấy điểm này. '
             'Thiếu điểm xuất phát là thiếu chặng kho → điểm đầu và chặng về.',
    )

    @api.constrains('dispatch_driver_user_id')
    def _check_one_vehicle_per_driver(self):
        """Một tài khoản chỉ gắn với MỘT xe.

        Hai xe cùng một tài khoản thì khi tài khoản đó quét nhận hàng, không biết hàng lên
        xe nào — và đối chiếu kế hoạch với thực tế sẽ ghép nhầm chuyến.
        """
        for vehicle in self.filtered('dispatch_driver_user_id'):
            other = self.search([
                ('id', '!=', vehicle.id),
                ('dispatch_driver_user_id', '=', vehicle.dispatch_driver_user_id.id),
            ], limit=1)
            if other:
                raise ValidationError(
                    'Tài khoản "%s" đã là tài xế của xe %s. Mỗi tài khoản chỉ gắn một xe — '
                    'gỡ ở xe kia trước.' % (
                        vehicle.dispatch_driver_name or vehicle.dispatch_driver_user_id.name,
                        other.license_plate or other.display_name,
                    )
                )

    def _dispatch_assignment_payload(self):
        """Khối ``assignment`` trả qua API: tài xế mặc định và điểm xuất phát mặc định."""
        self.ensure_one()
        user = self.dispatch_driver_user_id
        place = self.dispatch_start_place_id
        return {
            'driver_user_id': user.id or None,
            'driver_name': (self.dispatch_driver_name or user.name) if user else None,
            'start_place_id': place.id or None,
            'start_place_name': place.name or None,
        }
