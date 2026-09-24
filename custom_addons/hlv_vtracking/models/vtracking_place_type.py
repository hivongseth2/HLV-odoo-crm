from odoo import api, fields, models

# Màu mặc định khi người dùng không chọn. Không dùng màu của xe (xanh lá/vàng/xanh dương)
# để địa điểm không bị nhìn nhầm thành phương tiện.
DEFAULT_COLOR = '#7c3aed'


class HlvVtrackingPlaceType(models.Model):
    """Loại địa điểm — quyết định địa điểm hiện thế nào trên bản đồ.

    Là model chứ không phải Selection cứng: mỗi công ty có cách phân loại riêng (kho,
    đối tác, nhà cung cấp, bãi đỗ, trạm xăng...), và thêm một loại mới không đáng phải
    sửa code rồi nâng cấp module.
    """

    _name = 'hlv.vtracking.place.type'
    _description = 'Loại địa điểm'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        help='Mã ngắn, dùng khi lọc qua API. Để trống cũng được.',
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    color = fields.Char(
        string='Màu ghim', default=DEFAULT_COLOR, required=True,
        help='Mã màu dạng #rrggbb.',
    )
    size = fields.Selection(
        [('small', 'Nhỏ'), ('normal', 'Vừa'), ('large', 'Lớn — nổi bật')],
        string='Cỡ ghim', default='normal', required=True,
        help='Dùng "Lớn" cho loại phải nhìn thấy ngay giữa hàng trăm ghim khác, ví dụ kho.',
    )
    show_label = fields.Boolean(
        string='Luôn hiện tên', default=False,
        help='Hiện tên ngay cạnh ghim mà không cần rê chuột. Chỉ bật cho loại có ít địa '
             'điểm — bật cho loại có hàng trăm điểm thì bản đồ thành một mảng chữ.',
    )
    visible_by_default = fields.Boolean(
        string='Hiện sẵn trên bản đồ', default=True,
        help='Tắt thì loại này vẫn có trên bản đồ nhưng người xem phải tự bật lên.',
    )

    place_ids = fields.One2many('hlv.vtracking.place', 'type_id', string='Địa điểm')
    place_count = fields.Integer(compute='_compute_place_count')

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Đã có loại địa điểm trùng tên.'),
    ]

    @api.depends('place_ids')
    def _compute_place_count(self):
        grouped = {}
        if self.ids:
            for group in self.env['hlv.vtracking.place']._read_group(
                [('type_id', 'in', self.ids)], groupby=['type_id'], aggregates=['__count'],
            ):
                grouped[group[0].id] = group[1]
        for record in self:
            record.place_count = grouped.get(record.id, 0)

    def action_open_places(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Địa điểm — %s' % self.name,
            'res_model': 'hlv.vtracking.place',
            'view_mode': 'list,form',
            'domain': [('type_id', '=', self.id)],
            'context': {'default_type_id': self.id},
        }
