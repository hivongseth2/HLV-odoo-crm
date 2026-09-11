from odoo import fields, models


class FleetVehicle(models.Model):
    """Bổ sung thông số chở hàng cho xe.

    fleet core không có tải trọng hàng hoá hay kích thước khoang — ``seats`` là chỗ
    ngồi hành khách, không dùng thay số kiện được.
    """

    _inherit = 'fleet.vehicle'

    x_dispatch_enabled = fields.Boolean(
        string='Dùng cho điều phối', default=False, index=True,
        help='Chỉ xe bật cờ này mới xuất hiện khi xếp chuyến.',
    )
    x_dispatch_warehouse_id = fields.Many2one(
        'stock.warehouse', string='Kho phụ trách', index=True,
    )
    x_dispatch_role = fields.Selection(
        [
            ('van', 'Xe tải nhỏ / van'),
            ('truck', 'Xe tải lớn'),
            ('technical', 'Xe kỹ thuật'),
        ],
        string='Vai trò trong điều phối',
    )
    x_payload_kg = fields.Float(string='Tải trọng (kg)')
    x_cargo_length_m = fields.Float(string='Khoang: dài (m)')
    x_cargo_width_m = fields.Float(string='Khoang: rộng (m)')
    x_cargo_height_m = fields.Float(string='Khoang: cao (m)')
    x_max_item_length_m = fields.Float(
        string='Hàng dài tối đa (m)',
        help='Vượt ngưỡng này phải đổi sang xe tải lớn, và tài xế bỏ xe nhỏ sang lái xe tải '
             'nên số chuyến trong ngày giảm.',
    )
    x_max_pieces = fields.Integer(string='Số kiện chở thoải mái')
