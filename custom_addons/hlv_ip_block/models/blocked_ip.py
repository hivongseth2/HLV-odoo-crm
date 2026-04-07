from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class BlockedIP(models.Model):
    _name = 'hlv.blocked.ip'
    _description = 'Blocked IP Address'
    _order = 'create_date desc'

    name = fields.Char(string='Địa chỉ IP', required=True, index=True)
    reason = fields.Text(string='Lý do chặn')
    active = fields.Boolean(string='Đang kích hoạt', default=True)
    hit_count = fields.Integer(string='Số lần chặn', default=0, readonly=True)
    last_hit = fields.Datetime(string='Lần chặn cuối', readonly=True)
    is_auto = fields.Boolean(string='Tự động phát hiện', default=False, readonly=True)
    detection_type = fields.Selection([
        ('manual', 'Thủ công'),
        ('suspicious_path', 'Path đáng ngờ'),
        ('rate_limit', 'Quá nhiều request'),
    ], string='Loại phát hiện', default='manual', readonly=True)

    _sql_constraints = [
        ('unique_ip', 'UNIQUE(name)', 'Địa chỉ IP này đã tồn tại trong danh sách chặn!'),
    ]


class WhitelistedIP(models.Model):
    _name = 'hlv.whitelisted.ip'
    _description = 'Whitelisted IP Address'
    _order = 'create_date desc'

    name = fields.Char(string='Địa chỉ IP / CIDR', required=True, index=True)
    note = fields.Char(string='Ghi chú')

    _sql_constraints = [
        ('unique_ip', 'UNIQUE(name)', 'Địa chỉ IP này đã tồn tại trong whitelist!'),
    ]
