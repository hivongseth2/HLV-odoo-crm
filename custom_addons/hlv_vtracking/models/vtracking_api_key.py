import hmac
import logging
import secrets

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

KEY_BYTES = 32


class HlvVtrackingApiKey(models.Model):
    """Khoá để ứng dụng ngoài gọi API của module này.

    Một khoá cho MỖI ứng dụng, không dùng chung một khoá cho tất cả: ứng dụng nào rò rỉ
    thì thu hồi đúng ứng dụng đó, không phải đổi khoá cho mọi nơi đang dùng.

    Khoá này KHÔNG phải API key của vTracking (cái đó nằm ở cấu hình công ty). Đây là
    khoá Odoo cấp cho bên gọi vào.
    """

    _name = 'hlv.vtracking.api.key'
    _description = 'Khoá API vTracking cho ứng dụng ngoài'
    _order = 'name'

    name = fields.Char(
        string='Tên ứng dụng', required=True,
        help='Ghi rõ ai dùng khoá này, để sau còn biết thu hồi cái nào.',
    )
    key = fields.Char(
        string='Khoá', required=True, readonly=True, copy=False, index=True,
        default=lambda self: secrets.token_urlsafe(KEY_BYTES),
        groups='hlv_vtracking.group_vtracking_manager',
        help='Gửi lên trong header X-API-Key.',
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', string='Công ty', required=True, index=True,
        default=lambda self: self.env.company,
        help='Khoá chỉ đọc được xe của công ty này.',
    )
    note = fields.Text(string='Ghi chú')

    last_used_at = fields.Datetime(string='Dùng lần cuối', readonly=True, copy=False)
    last_used_ip = fields.Char(string='IP lần cuối', readonly=True, copy=False)
    request_count = fields.Integer(string='Số lượt gọi', readonly=True, copy=False, default=0)

    _sql_constraints = [
        ('key_uniq', 'unique(key)', 'Khoá API bị trùng.'),
    ]

    def action_regenerate(self):
        """Cấp lại khoá. Ứng dụng đang dùng khoá cũ sẽ mất quyền ngay lập tức."""
        for record in self:
            record.key = secrets.token_urlsafe(KEY_BYTES)
        return True

    @api.model
    def authenticate(self, raw_key):
        """Khoá thô -> bản ghi khoá hợp lệ, hoặc recordset rỗng.

        So sánh bằng ``hmac.compare_digest`` trên từng ứng viên thay vì tìm thẳng bằng
        domain: tìm bằng domain sẽ để lộ khoá đúng qua thời gian phản hồi.
        """
        if not raw_key:
            return self.browse()
        candidates = self.sudo().with_context(active_test=True).search([])
        for candidate in candidates:
            if hmac.compare_digest(candidate.key or '', raw_key):
                return candidate
        return self.browse()

    def mark_used(self, remote_ip=None):
        """Ghi nhận một lượt gọi. Lỗi ghi nhật ký không được làm hỏng lời gọi API."""
        self.ensure_one()
        try:
            self.sudo().write({
                'last_used_at': fields.Datetime.now(),
                'last_used_ip': remote_ip or False,
                'request_count': (self.request_count or 0) + 1,
            })
        except Exception:  # noqa: BLE001 — nhật ký hỏng không đáng để trả lỗi cho app gọi
            _logger.warning('vTracking: không ghi được nhật ký dùng khoá %s.', self.name)
        return True

    @api.ondelete(at_uninstall=False)
    def _unlink_warn_in_use(self):
        """Chặn xoá khoá đang được dùng — vô hiệu hoá thì ứng dụng còn báo lỗi rõ ràng."""
        for record in self:
            if record.request_count:
                raise UserError(
                    'Khoá "%s" đã được dùng %s lượt. Hãy bỏ tick "Đang dùng" để thu hồi '
                    'thay vì xoá, để còn tra lại được sau này.'
                    % (record.name, record.request_count)
                )
