import json
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class DeliveryPlannerUserPref(models.Model):
    """Per-user preferences for the Delivery Planner dashboard.

    Stores:
      - archived_so_ids: SOs the user hàs "cất" (không còn dùng / bỏ
        khỏi danh sách).
      - consolidate_so_ids: SOs the user đặt vào "chờ gom đơn" — đồng
        nghĩa với tạm ẩn khỏi kế hoạch giao hôm nay nhưng vẫn
        giữ lại để gộp chuyến sau.
      - default_filters_json: snapshot of the filter form the user wants to
        apply automatically on dashboard open.

    Cả archived lẫn consolidate đều được loại khỏi kế hoạch AI
    Dispatcher.
    """
    _name = 'hlv.delivery.planner.user.pref'
    _description = 'Delivery Planner — User Preferences'
    _rec_name = 'user_id'

    user_id = fields.Many2one(
        'res.users', string='User', required=True, ondelete='cascade', index=True,
        default=lambda self: self.env.user.id,
    )
    archived_so_ids = fields.Many2many(
        'sale.order', 'hlv_dp_user_pref_archived_so_rel',
        'pref_id', 'sale_order_id', string='Đơn đã cất (không dùng)',
    )
    consolidate_so_ids = fields.Many2many(
        'sale.order', 'hlv_dp_user_pref_consolidate_so_rel',
        'pref_id', 'sale_order_id', string='Đơn chờ gom',
        help='Đơn đã đóng gói chờ khách xác nhận / chờ gom thêm để đi 1 chuyến.',
    )
    default_filters_json = fields.Text(
        string='Bộ lọc mặc định (JSON)', default='{}',
    )

    _sql_constraints = [
        ('user_uniq', 'unique(user_id)', 'Mỗi user chỉ có 1 bản ghi preference.'),
    ]

    @api.model
    def _get_or_create_for_current_user(self):
        rec = self.sudo().search([('user_id', '=', self.env.uid)], limit=1)
        if not rec:
            rec = self.sudo().create({'user_id': self.env.uid})
        return rec

    # ---------------- Public RPC API ----------------

    @api.model
    def get_user_preferences(self):
        """Return current user's archived + consolidate SO ids + default filters."""
        rec = self._get_or_create_for_current_user()
        # Filter out SOs that no longer exist (cancelled/deleted).
        existing_archived = rec.archived_so_ids.exists().ids
        if len(existing_archived) != len(rec.archived_so_ids):
            rec.sudo().write({'archived_so_ids': [(6, 0, existing_archived)]})
        existing_consolidate = rec.consolidate_so_ids.exists().ids
        if len(existing_consolidate) != len(rec.consolidate_so_ids):
            rec.sudo().write({'consolidate_so_ids': [(6, 0, existing_consolidate)]})
        try:
            default_filters = json.loads(rec.default_filters_json or '{}')
        except (ValueError, TypeError):
            default_filters = {}
        return {
            'archived_so_ids': existing_archived,
            'consolidate_so_ids': existing_consolidate,
            'default_filters': default_filters,
        }

    @api.model
    def toggle_archive(self, so_id):
        """Toggle archive state for a single SO. Returns the new full set.

        Nếu đơn đang ở bucket 'consolidate' (chờ gom) và user bấm
        archive → tự chuyển sang archive (1 đơn chỉ ở 1 bucket).
        """
        if not so_id:
            return self._snapshot()
        so_id = int(so_id)
        rec = self._get_or_create_for_current_user()
        current = set(rec.archived_so_ids.ids)
        consolidate = set(rec.consolidate_so_ids.ids)
        if so_id in current:
            current.discard(so_id)
        else:
            if self.env['sale.order'].browse(so_id).exists():
                current.add(so_id)
                consolidate.discard(so_id)
        rec.sudo().write({
            'archived_so_ids': [(6, 0, list(current))],
            'consolidate_so_ids': [(6, 0, list(consolidate))],
        })
        return self._snapshot(rec)

    @api.model
    def toggle_consolidate(self, so_id):
        """Toggle consolidate (chờ gom) state for a single SO.

        Nếu đơn đang ở bucket archive → tự chuyển sang consolidate.
        """
        if not so_id:
            return self._snapshot()
        so_id = int(so_id)
        rec = self._get_or_create_for_current_user()
        current = set(rec.consolidate_so_ids.ids)
        archived = set(rec.archived_so_ids.ids)
        if so_id in current:
            current.discard(so_id)
        else:
            if self.env['sale.order'].browse(so_id).exists():
                current.add(so_id)
                archived.discard(so_id)
        rec.sudo().write({
            'consolidate_so_ids': [(6, 0, list(current))],
            'archived_so_ids': [(6, 0, list(archived))],
        })
        return self._snapshot(rec)

    @api.model
    def set_archived(self, so_ids):
        """Replace the archived set (used by 'phục hồi tất cả' / bulk ops)."""
        ids = [int(i) for i in (so_ids or []) if i]
        rec = self._get_or_create_for_current_user()
        rec.sudo().write({'archived_so_ids': [(6, 0, ids)]})
        return self._snapshot(rec)

    @api.model
    def set_consolidate(self, so_ids):
        """Replace the consolidate set (used by 'phục hồi tất cả' / bulk ops)."""
        ids = [int(i) for i in (so_ids or []) if i]
        rec = self._get_or_create_for_current_user()
        rec.sudo().write({'consolidate_so_ids': [(6, 0, ids)]})
        return self._snapshot(rec)

    def _snapshot(self, rec=None):
        rec = rec or self._get_or_create_for_current_user()
        return {
            'archived_so_ids': rec.archived_so_ids.ids,
            'consolidate_so_ids': rec.consolidate_so_ids.ids,
        }

    @api.model
    def save_default_filters(self, filters):
        """Persist the given filter dict as the user's default."""
        if not isinstance(filters, dict):
            filters = {}
        rec = self._get_or_create_for_current_user()
        rec.sudo().write({'default_filters_json': json.dumps(filters, ensure_ascii=False)})
        return {'ok': True}

    @api.model
    def clear_default_filters(self):
        rec = self._get_or_create_for_current_user()
        rec.sudo().write({'default_filters_json': '{}'})
        return {'ok': True}
