from odoo import fields, models
from odoo.exceptions import UserError

from ..services.vtracking_sync import get_client
from ..services.vtracking_client import VTrackingError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    vtracking_base_url = fields.Char(
        related='company_id.vtracking_base_url', readonly=False,
    )
    vtracking_api_key = fields.Char(
        related='company_id.vtracking_api_key', readonly=False,
    )
    vtracking_verify_ssl = fields.Boolean(
        related='company_id.vtracking_verify_ssl', readonly=False,
    )
    vtracking_expand_children = fields.Boolean(
        related='company_id.vtracking_expand_children', readonly=False,
    )
    vtracking_timeout = fields.Integer(
        related='company_id.vtracking_timeout', readonly=False,
    )
    vtracking_retention_days = fields.Integer(
        related='company_id.vtracking_retention_days', readonly=False,
    )
    vtracking_map_tile_url = fields.Char(
        related='company_id.vtracking_map_tile_url', readonly=False,
    )
    vtracking_map_attribution = fields.Char(
        related='company_id.vtracking_map_attribution', readonly=False,
    )

    def action_vtracking_test_connection(self):
        """Gọi thử một request nhỏ nhất và báo kết quả.

        Lưu cấu hình trước khi thử: người dùng vừa gõ khoá vào ô mà chưa bấm Lưu thì
        client dựng từ ``company_id`` sẽ vẫn dùng khoá cũ và báo sai.
        """
        self.ensure_one()
        self.execute()
        try:
            result = get_client(self.company_id).ping()
        except VTrackingError as exc:
            raise UserError(str(exc)) from exc
        message = 'Kết nối được. vTracking báo có %s xe trong tài khoản.' % result['total']
        if result['sample_plate']:
            message += ' Ví dụ: %s.' % result['sample_plate']
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'vTracking',
                'message': message,
                'type': 'success',
                'sticky': False,
            },
        }
