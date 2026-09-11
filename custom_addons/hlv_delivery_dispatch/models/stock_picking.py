from odoo import fields, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    x_trip_id = fields.Many2one(
        'hlv.delivery.trip', string='Chuyến', index=True,
        help='Gán phiếu cho chuyến để đối chiếu kế hoạch với thực tế. Không suy gián tiếp '
             'qua shipper_user_id + ngày vì một tài xế có thể chạy nhiều chuyến trong ngày, '
             'và tài khoản tài xế thuê ngoài là tài khoản dùng chung.',
    )
