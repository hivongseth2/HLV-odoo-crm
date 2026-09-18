from odoo import api, fields, models

# Giá trị lùi khi cụm chưa khai định mức. Lấy từ trung vị đo được trên 332 chuyến
# (01/06 → 10/09/2026) — xem plan/ke-hoach-ai-dieu-phoi.md §1.2.
DEFAULT_HUB_MINUTES = 42
DEFAULT_LEG_MINUTES = 15
DEFAULT_RETURN_MINUTES = 30
DEFAULT_MAX_STOPS = 8


class HlvVtrackingZone(models.Model):
    """Cụm tuyến giao hàng — nơi ở của định mức thời gian.

    Vì sao định mức phải nằm ở CỤM chứ không ở công ty: đối chiếu kế hoạch với thực tế
    ngày 11/09 bắt được rằng dùng chung trung vị 42 phút cho mọi cụm là sai — Nhơn Trạch
    thật ra 40 phút còn Long Thành 57 phút. Một con số chung cho cả Nhơn Trạch lẫn Vũng
    Tàu thì mọi kế hoạch đều lệch, và lệch theo hướng không đoán được.

    Đây cũng là nơi vòng học ghi kết quả về: sau mỗi lần đối chiếu, định mức của cụm được
    đề xuất sửa lại. Nhét các con số này vào prompt hay vào code là chặn đứng vòng đó.
    """

    _name = 'hlv.vtracking.zone'
    _description = 'Cụm tuyến giao hàng'
    _order = 'warehouse_id, sequence, id'

    name = fields.Char(required=True, index=True)
    code = fields.Char(help='Mã ngắn dùng khi đặt tên chuyến, ví dụ NT, LABS, MXPM.')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    color = fields.Char(
        string='Màu trên bản đồ', default='#2563eb',
        help='Mã màu dạng #rrggbb, dùng khi tô các điểm của cụm.',
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Kho xuất phát', index=True, ondelete='set null',
        help='Định mức "kho → điểm đầu" tính từ kho này. Để trống vẫn dùng được định mức '
             '— nhưng gán vào thì lọc chứng từ theo kho mới chạy đúng.',
    )
    company_id = fields.Many2one(
        'res.company', required=True, index=True, default=lambda self: self.env.company,
    )

    # --- Định mức thời gian -------------------------------------------------
    hub_to_first_minutes = fields.Integer(
        string='Kho → điểm đầu (phút)', default=DEFAULT_HUB_MINUTES,
        help='Gồm cả thời gian xếp nốt hàng lên xe sau khi tài xế nhận, nên luôn lớn hơn '
             'thời gian chạy thuần. Đo được: Nhơn Trạch 40, Long Thành – Bình Sơn 57.',
    )
    median_leg_minutes = fields.Integer(
        string='Điểm → điểm (phút)', default=DEFAULT_LEG_MINUTES,
        help='Trung vị thời gian giữa hai điểm liên tiếp trong cụm, đã gồm bốc dỡ và ký '
             'nhận. Đo toàn hệ: p25 9,2 · trung vị 15,8 · p75 30,2.',
    )
    return_minutes = fields.Integer(
        string='Điểm cuối → về kho (phút)', default=DEFAULT_RETURN_MINUTES,
        help='Cụm xa thì chặng về đáng kể: Mỹ Xuân 65 phút, Châu Đức – Vũng Tàu 80 phút.',
    )
    max_stops = fields.Integer(
        string='Trần điểm/chuyến', default=DEFAULT_MAX_STOPS,
        help='Trần MỀM — vượt chỉ cảnh báo, không chặn. Điều phối vẫn có quyền xếp thêm.',
    )
    min_stops_worth_trip = fields.Integer(
        string='Ít nhất bao nhiêu điểm mới đáng chạy', default=2,
        help='Dưới ngưỡng này thì nên gộp sang chuyến khác hoặc gửi chuyển phát nhanh. '
             '65 trong 332 chuyến đo được chỉ có ĐÚNG MỘT điểm — mỗi chuyến như vậy tốn '
             'cả chặng kho → cụm cho một lần giao.',
    )

    note = fields.Text(string='Ghi chú')

    place_ids = fields.One2many('hlv.vtracking.place', 'zone_id', string='Điểm giao')
    place_count = fields.Integer(compute='_compute_place_count')

    _sql_constraints = [
        ('name_company_uniq', 'unique(name, company_id)',
         'Công ty không được có hai cụm tuyến trùng tên.'),
    ]

    @api.depends('place_ids')
    def _compute_place_count(self):
        grouped = {}
        if self.ids:
            for group in self.env['hlv.vtracking.place']._read_group(
                [('zone_id', 'in', self.ids)], groupby=['zone_id'], aggregates=['__count'],
            ):
                grouped[group[0].id] = group[1]
        for zone in self:
            zone.place_count = grouped.get(zone.id, 0)

    def route_params(self):
        """Định mức của cụm ở dạng dict, dùng cho ``tools/vtracking_route``.

        Không trả ``speed_kmh``: cụm khai thời gian MỖI CHẶNG đo được từ thực tế, chính
        xác hơn là suy ngược từ tốc độ trung bình. Kế hoạch dùng cụm thì tính theo số
        chặng; chưa gán cụm mới lùi về tốc độ chung của công ty.
        """
        self.ensure_one()
        return {
            'hub_to_first_minutes': self.hub_to_first_minutes or DEFAULT_HUB_MINUTES,
            'median_leg_minutes': self.median_leg_minutes or DEFAULT_LEG_MINUTES,
            'return_minutes': self.return_minutes or DEFAULT_RETURN_MINUTES,
            'max_stops': self.max_stops or DEFAULT_MAX_STOPS,
            'min_stops_worth_trip': self.min_stops_worth_trip or 0,
        }

    def action_open_places(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Điểm giao — %s' % self.name,
            'res_model': 'hlv.vtracking.place',
            'view_mode': 'list,form',
            'domain': [('zone_id', '=', self.id)],
            'context': {'default_zone_id': self.id},
        }
