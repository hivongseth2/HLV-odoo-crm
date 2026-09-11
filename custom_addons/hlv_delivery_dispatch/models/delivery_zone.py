from odoo import api, fields, models


class HlvDeliveryZone(models.Model):
    """Cụm tuyến giao hàng.

    Lớp trên Google My Maps KHÔNG dùng làm cụm được: trong 5 lớp của bản đồ hiện tại
    có 2 lớp không phải cụm (một lớp chỉ đường, một lớp ghi quy tắc CPN), còn
    Châu Đức–Vũng Tàu và HCM thì chưa có lớp nào. Vì vậy cụm là model độc lập,
    khai báo tay; import bản đồ chỉ *gợi ý* cụm chứ không gán cứng.
    """

    _name = 'hlv.delivery.zone'
    _description = 'Cụm tuyến giao hàng'
    _order = 'warehouse_id, sequence, id'

    name = fields.Char(required=True, index=True)
    code = fields.Char(help='Mã ngắn dùng khi đặt tên chuyến, VD: NT, LABS, MXPM.')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    color = fields.Integer(string='Màu')
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Kho', required=True, index=True, ondelete='cascade',
    )
    company_id = fields.Many2one(related='warehouse_id.company_id', store=True, index=True)

    hub_to_first_minutes = fields.Integer(
        string='Kho → điểm đầu (phút)', default=42,
        help='Thời gian từ kho tới điểm giao đầu tiên của cụm này. Phải khai theo từng cụm '
             '(Nhơn Trạch ~40 phút, Long Thành ~57 phút) — dùng trung vị chung 42 phút cho '
             'mọi cụm là sai, đây là một trong ba lỗi rút ra khi so kế hoạch với thực tế.',
    )
    median_leg_minutes = fields.Integer(
        string='Điểm → điểm (phút)', default=16,
        help='Trung vị thời gian di chuyển giữa 2 điểm liên tiếp trong cụm. '
             'Đo toàn hệ: p25 9.2 / trung vị 15.8 / p75 30.2 phút.',
    )
    max_stops = fields.Integer(
        string='Trần số điểm/chuyến', default=8,
        help='Trần MỀM — vượt trần chỉ cảnh báo, không chặn xếp chuyến.',
    )

    point_ids = fields.One2many('hlv.delivery.point', 'zone_id', string='Điểm giao')
    point_count = fields.Integer(compute='_compute_point_count')

    _sql_constraints = [
        ('name_warehouse_uniq', 'unique(name, warehouse_id)',
         'Mỗi kho không được có 2 cụm tuyến trùng tên.'),
    ]

    @api.depends('point_ids')
    def _compute_point_count(self):
        grouped = {}
        if self.ids:
            for group in self.env['hlv.delivery.point']._read_group(
                [('zone_id', 'in', self.ids)], groupby=['zone_id'], aggregates=['__count'],
            ):
                grouped[group[0].id] = group[1]
        for zone in self:
            zone.point_count = grouped.get(zone.id, 0)

    def action_open_points(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Điểm giao — %s' % self.name,
            'res_model': 'hlv.delivery.point',
            'view_mode': 'list,form',
            'domain': [('zone_id', '=', self.id)],
            'context': {'default_zone_id': self.id},
        }
