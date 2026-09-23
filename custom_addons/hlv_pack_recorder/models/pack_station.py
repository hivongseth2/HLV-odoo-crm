# -*- coding: utf-8 -*-
"""Bàn đóng gói: một máy tính, một bộ camera, một agent ghi hình."""
import secrets

from odoo import api, fields, models


class HlvPackStation(models.Model):
    _name = 'hlv.pack.station'
    _description = "Bàn đóng gói"
    _order = 'warehouse_id, name'

    name = fields.Char("Tên bàn", required=True)
    warehouse_id = fields.Many2one('stock.warehouse', string="Kho", required=True)
    active = fields.Boolean(default=True)

    station_key = fields.Char(
        "Mã máy", required=True, copy=False, index=True,
        default=lambda self: self._default_station_key(),
        help="Trình duyệt trên máy đóng gói lưu mã này và gửi kèm mỗi lần mở phiếu. "
             "Đặt một lần bằng /pack_recorder/set_station?key=<mã>.",
    )
    # Để trong group_system: token là thứ duy nhất chặn người lạ gọi API agent.
    agent_token = fields.Char(
        "Token agent", required=True, copy=False, groups='base.group_system',
        default=lambda self: secrets.token_urlsafe(32),
        help="Agent gửi kèm token này mỗi lần gọi. Sinh lại token là agent cũ mất quyền ngay.",
    )

    camera_ids = fields.One2many('hlv.pack.camera', 'station_id', string="Camera")
    camera_count = fields.Integer(compute='_compute_camera_count')

    agent_last_seen = fields.Datetime(
        "Agent gọi lần cuối", readonly=True,
        help="Agent im quá lâu nghĩa là máy tắt hoặc service chết — phiếu đóng gói ở bàn này sẽ không có video.",
    )
    agent_version = fields.Char(readonly=True)

    _sql_constraints = [
        ('station_key_uniq', 'unique(station_key)', "Mã máy phải là duy nhất."),
    ]

    @api.model
    def _default_station_key(self):
        return 'BAN-%s' % secrets.token_hex(3).upper()

    @api.depends('camera_ids')
    def _compute_camera_count(self):
        for station in self:
            station.camera_count = len(station.camera_ids)

    def action_reset_token(self):
        """Sinh token mới. Agent đang chạy sẽ bị từ chối cho tới khi cập nhật token."""
        for station in self:
            station.agent_token = secrets.token_urlsafe(32)

    @api.model
    def _authenticate(self, station_key, token):
        """Tra bàn đóng gói từ cặp mã máy + token của agent.

        station_key: chuỗi mã máy agent gửi lên.
        token: chuỗi token agent gửi lên.
        Trả về: recordset một bàn nếu khớp, recordset rỗng nếu sai hoặc thiếu.
            So sánh bằng compare_digest để không lộ token qua thời gian phản hồi.
        """
        if not station_key or not token:
            return self.browse()
        station = self.sudo().search([('station_key', '=', station_key)], limit=1)
        if not station:
            return self.browse()
        if not secrets.compare_digest(str(station.agent_token or ''), str(token)):
            return self.browse()
        return station
