"""Xe chở được gì — thứ điều phối cần biết mà module Đội xe không có.

Tách khỏi ``fleet_vehicle.py``: file đó lo định vị (vTracking), file này lo chuyên chở.
Hai việc khác nhau, thay đổi vì những lý do khác nhau.

Vì sao cần: AI lập kế hoạch chỉ thấy biển số và mẫu xe "Chưa rõ" thì không phân biệt được
xe nào là Kim Long 950 kg, xe nào là EC Van 650 kg, xe nào chỉ dùng khi hàng dài quá 4 m.
Nó sẽ chọn bừa — và chọn bừa xe cho đơn hàng thép 6 m là tài xế tới nơi mới biết không chở
được. ``seats`` của Đội xe là chỗ ngồi hành khách, không dùng thay số kiện được.
"""

from odoo import fields, models

DISPATCH_ROLES = [
    ('van', 'Xe tải nhỏ / van — chạy tuyến hằng ngày'),
    ('truck', 'Xe tải lớn — chỉ dùng khi hàng quá khổ'),
    ('technical', 'Xe kỹ thuật — đi lắp đặt'),
    ('motorbike', 'Xe máy — hàng nhẹ, gấp'),
]


class FleetVehicleCapacity(models.Model):
    _inherit = 'fleet.vehicle'

    dispatch_role = fields.Selection(
        DISPATCH_ROLES, string='Vai trò khi xếp chuyến',
        help='AI đọc ô này để biết xe nào chạy tuyến thường ngày, xe nào chỉ dùng cho hàng '
             'quá khổ. Để trống thì AI coi như không biết và sẽ hỏi lại.',
    )
    dispatch_payload_kg = fields.Float(string='Tải trọng (kg)')
    dispatch_cargo_length_m = fields.Float(string='Thùng: dài (m)')
    dispatch_cargo_width_m = fields.Float(string='Thùng: rộng (m)')
    dispatch_cargo_height_m = fields.Float(string='Thùng: cao (m)')
    dispatch_max_item_length_m = fields.Float(
        string='Hàng dài tối đa (m)',
        help='Kiện dài hơn số này thì phải đổi xe. Thường lớn hơn chiều dài thùng vì hàng '
             'dài được thò ra sau.',
    )
    dispatch_max_pieces = fields.Integer(
        string='Số kiện chở thoải mái',
        help='Odoo không tính được tải từ cân nặng (phần lớn sản phẩm không khai cân nặng), '
             'nên đếm kiện là cách ước lượng duy nhất đang dùng được.',
    )
    dispatch_note = fields.Text(
        string='Mô tả cho điều phối',
        help='Viết như dặn một người điều phối mới: xe này dùng khi nào, không dùng khi nào, '
             'ai hay lái. AI đọc nguyên văn ô này trước khi chọn xe.',
    )

    def _dispatch_capacity_payload(self):
        """Khối ``capacity`` trả qua API cho AI. Ô trống trả ``None`` chứ không trả 0 —
        0 kg nghĩa là "không chở được gì", còn None nghĩa là "chưa ai khai", hai chuyện
        khác hẳn nhau khi AI quyết định chọn xe."""
        self.ensure_one()

        def value(number):
            return number or None

        return {
            'role': self.dispatch_role or None,
            'role_label': dict(DISPATCH_ROLES).get(self.dispatch_role) if self.dispatch_role else None,
            'payload_kg': value(self.dispatch_payload_kg),
            'cargo_m': {
                'length': value(self.dispatch_cargo_length_m),
                'width': value(self.dispatch_cargo_width_m),
                'height': value(self.dispatch_cargo_height_m),
            },
            'max_item_length_m': value(self.dispatch_max_item_length_m),
            'max_pieces': value(self.dispatch_max_pieces),
            'note': (self.dispatch_note or '').strip() or None,
            'declared': bool(self.dispatch_role or self.dispatch_payload_kg or self.dispatch_note),
        }
