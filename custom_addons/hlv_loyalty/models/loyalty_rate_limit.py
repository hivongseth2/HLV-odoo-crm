# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models


class LoyaltyRateLimitHit(models.Model):
    """Một lượt gọi API công khai, dùng để giới hạn tần suất theo IP.

    Lưu trong DB chứ không đếm trong RAM: Odoo.sh chạy nhiều worker, bộ đếm
    trong RAM của mỗi worker riêng nên giới hạn thực tế bị nhân lên theo số worker.
    """
    _name = 'hlv.loyalty.rate.limit.hit'
    _description = 'Loyalty API rate limit hit'
    _log_access = False

    key = fields.Char(required=True, index=True)
    hit_at = fields.Datetime(required=True, index=True, default=fields.Datetime.now)

    # Lượt cũ hơn mọi cửa sổ đang dùng; autovacuum dọn sau mốc này.
    _RETENTION = timedelta(days=1)

    @api.model
    def consume(self, key, limit, window_seconds):
        """Ghi một lượt cho `key`; trả False nếu trong `window_seconds` vừa qua
        đã có từ `limit` lượt trở lên (lượt bị từ chối không được ghi)."""
        since = fields.Datetime.now() - timedelta(seconds=window_seconds)
        if self.search_count([('key', '=', key), ('hit_at', '>=', since)]) >= limit:
            return False
        self.create({'key': key})
        return True

    @api.autovacuum
    def _gc_old_hits(self):
        self.search([('hit_at', '<', fields.Datetime.now() - self._RETENTION)]).unlink()
