# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models

from .zalo_utils import clip, ts_to_utc

# Máy nghe gửi trạng thái mỗi phút; quá chừng này không thấy là máy nghe chết / mất mạng / tắt máy.
STALE_MINUTES = 10
LISTENER_STATES = [
    ("connected", "Đang nghe"),
    ("reconnecting", "Đang nối lại"),
    ("login_wait", "Chờ đăng nhập"),
    ("kicked", "Bị Zalo đá ra — cần người xem"),
    ("stopped", "Đã dừng"),
]


class ZaloListener(models.Model):
    """Trạng thái máy nghe báo về kèm mỗi lô tin — để biết máy nghe còn sống, rớt bao nhiêu lần, vì sao. Tài liệu
    vận hành cũ: phải có số đo (giờ + mã lỗi) chứ đừng đoán nguyên nhân rớt."""

    _name = "hlv.zalo.listener"
    _description = "Máy nghe Zalo"
    _order = "last_seen_at desc"

    name = fields.Char(string="Máy nghe", required=True, readonly=True)
    state = fields.Selection(LISTENER_STATES, string="Trạng thái", readonly=True)
    last_seen_at = fields.Datetime(string="Báo về lần cuối", readonly=True)
    is_stale = fields.Boolean(string="Mất liên lạc", compute="_compute_is_stale")
    connected_since = fields.Datetime(string="Nối từ", readonly=True)
    last_close_code = fields.Integer(string="Mã rớt gần nhất", readonly=True,
                                     help="1006: Zalo cắt kết nối; 3000: tài khoản đang mở ở chỗ khác; 3003: bị đá ra "
                                          "(đổi mật khẩu / đăng nhập thiết bị mới).")
    last_close_at = fields.Datetime(string="Rớt lúc", readonly=True)
    drops_today = fields.Integer(string="Số lần rớt hôm nay", readonly=True)
    outbox = fields.Integer(string="Tin chờ gửi lên Odoo", readonly=True)
    version = fields.Char(string="Phiên bản", readonly=True)
    last_error = fields.Char(string="Lỗi gần nhất", readonly=True)

    _sql_constraints = [("name_unique", "unique(name)", "Mỗi máy nghe một bản ghi.")]

    @api.depends("last_seen_at")
    def _compute_is_stale(self):
        limit = fields.Datetime.now() - timedelta(minutes=STALE_MINUTES)
        for listener in self:
            listener.is_stale = not listener.last_seen_at or listener.last_seen_at < limit

    @api.model
    def _report(self, name, status):
        """Ghi trạng thái máy nghe gửi kèm lô tin. status: dict từ máy nghe (khoá lạ bỏ qua)."""
        name = clip(name, 64) or "may-nghe"
        status = status if isinstance(status, dict) else {}
        listener = self.search([("name", "=", name)], limit=1) or self.create({"name": name})
        state = status.get("state")
        vals = {
            "last_seen_at": fields.Datetime.now(),
            "state": state if state in dict(LISTENER_STATES) else listener.state,
            "connected_since": ts_to_utc(status.get("connected_since")) or False,
            "drops_today": int(status.get("drops_today") or 0),
            "outbox": int(status.get("outbox") or 0),
            "version": clip(status.get("version"), 32) or listener.version,
            "last_error": clip(status.get("last_error"), 255) or False,
        }
        if status.get("last_close_code"):
            vals.update(last_close_code=int(status["last_close_code"]),
                        last_close_at=ts_to_utc(status.get("last_close_at")) or False)
        listener.write(vals)
        return listener
