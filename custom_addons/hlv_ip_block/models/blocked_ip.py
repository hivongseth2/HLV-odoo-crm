from odoo import models, fields, api
from functools import lru_cache
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

    _sql_constraints = [
        ('unique_ip', 'UNIQUE(name)', 'Địa chỉ IP này đã tồn tại trong danh sách chặn!'),
    ]

    @api.model
    def is_blocked(self, ip_address):
        """Check if an IP address is blocked. Uses cache for performance."""
        blocked_ips = self._get_blocked_ips()
        return ip_address in blocked_ips

    @api.model
    def _get_blocked_ips(self):
        """Return set of blocked IPs. Cached for performance."""
        self.env.cr.execute(
            "SELECT name FROM hlv_blocked_ip WHERE active = TRUE"
        )
        return {row[0] for row in self.env.cr.fetchall()}

    @api.model
    def increment_hit(self, ip_address):
        """Increment the hit counter for a blocked IP."""
        self.env.cr.execute(
            """
            UPDATE hlv_blocked_ip
            SET hit_count = hit_count + 1, last_hit = NOW() AT TIME ZONE 'UTC'
            WHERE name = %s AND active = TRUE
            """,
            (ip_address,)
        )
