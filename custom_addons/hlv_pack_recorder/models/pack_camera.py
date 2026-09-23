# -*- coding: utf-8 -*-
"""Camera gắn với một bàn đóng gói.

Cố ý KHÔNG có trường URL/mật khẩu RTSP. Agent giữ phần đó trong file cấu hình
tại chỗ, Odoo chỉ biết mã camera. Nhờ vậy token agent hay database rò ra ngoài
cũng không kéo theo quyền xem camera kho.
"""
from odoo import api, fields, models


class HlvPackCamera(models.Model):
    _name = 'hlv.pack.camera'
    _description = "Camera bàn đóng gói"
    _order = 'station_id, sequence, id'

    name = fields.Char("Tên hiển thị", required=True, help="Ví dụ: Góc ngang, Góc trên.")
    code = fields.Char(
        "Mã camera", required=True,
        help="Phải trùng với khoá trong file cấu hình của agent. Ví dụ: ngang, tren.",
    )
    station_id = fields.Many2one(
        'hlv.pack.station', string="Bàn đóng gói",
        required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_per_station_uniq', 'unique(station_id, code)',
         "Mỗi bàn không được có hai camera trùng mã."),
    ]

    @api.depends('name', 'station_id.name')
    def _compute_display_name(self):
        for camera in self:
            camera.display_name = '%s / %s' % (camera.station_id.name or '', camera.name or '')
