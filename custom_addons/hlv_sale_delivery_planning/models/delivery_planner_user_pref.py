import json
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

_PARAM_GLOBAL_ARCHIVED = 'hlv_dp.global_archived_so_ids'
_PARAM_GLOBAL_CONSOLIDATE = 'hlv_dp.global_consolidate_so_ids'


class DeliveryPlannerUserPref(models.Model):
    """Per-user preferences for the Delivery Planner dashboard.

        Stores:
            - archived/consolidate buckets: GLOBAL cho toàn hệ thống (shared giữa
                các user), lưu trong ir.config_parameter.
            - default_filters_json: snapshot filter riêng theo từng user.

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

    @api.model
    def _sanitize_so_ids(self, ids):
        raw_ids = []
        for value in (ids or []):
            try:
                i = int(value)
            except (TypeError, ValueError):
                continue
            if i > 0:
                raw_ids.append(i)
        if not raw_ids:
            return []
        return self.env['sale.order'].sudo().browse(list(set(raw_ids))).exists().ids

    @api.model
    def _get_global_bucket_ids(self, param_key):
        ICP = self.env['ir.config_parameter'].sudo()
        try:
            data = json.loads(ICP.get_param(param_key, '[]') or '[]')
        except (ValueError, TypeError):
            data = []
        return self._sanitize_so_ids(data)

    @api.model
    def _set_global_bucket_ids(self, param_key, so_ids):
        clean_ids = self._sanitize_so_ids(so_ids)
        self.env['ir.config_parameter'].sudo().set_param(
            param_key, json.dumps(clean_ids)
        )
        return clean_ids

    @api.model
    def _bootstrap_global_buckets_from_legacy(self):
        """One-time migration helper from old per-user bucket fields."""
        records = self.sudo().search([])
        if not records:
            return set(), set()
        archived = set(records.mapped('archived_so_ids').ids)
        consolidate = set(records.mapped('consolidate_so_ids').ids)
        consolidate -= archived
        archived, consolidate = self._save_global_buckets(archived, consolidate)
        return archived, consolidate

    @api.model
    def _get_global_buckets(self):
        archived = set(self._get_global_bucket_ids(_PARAM_GLOBAL_ARCHIVED))
        consolidate = set(self._get_global_bucket_ids(_PARAM_GLOBAL_CONSOLIDATE))
        if not archived and not consolidate:
            archived, consolidate = self._bootstrap_global_buckets_from_legacy()
        overlap = archived.intersection(consolidate)
        if overlap:
            # Keep archive as winner on overlap to preserve old behavior.
            consolidate -= overlap
            self._set_global_bucket_ids(_PARAM_GLOBAL_ARCHIVED, list(archived))
            self._set_global_bucket_ids(_PARAM_GLOBAL_CONSOLIDATE, list(consolidate))
        return archived, consolidate

    @api.model
    def _save_global_buckets(self, archived, consolidate):
        archived = set(self._sanitize_so_ids(list(archived)))
        consolidate = set(self._sanitize_so_ids(list(consolidate)))
        consolidate -= archived
        archived_ids = self._set_global_bucket_ids(_PARAM_GLOBAL_ARCHIVED, list(archived))
        consolidate_ids = self._set_global_bucket_ids(_PARAM_GLOBAL_CONSOLIDATE, list(consolidate))
        return set(archived_ids), set(consolidate_ids)

    @api.model
    def _broadcast_pref_changed(self, snapshot, action='update', so_id=False):
        payload = {
            'action': action,
            'so_id': int(so_id) if so_id else False,
            'actor_uid': self.env.uid,
            'archived_so_ids': snapshot.get('archived_so_ids', []),
            'consolidate_so_ids': snapshot.get('consolidate_so_ids', []),
        }
        try:
            self.env['bus.bus']._sendone(
                'delivery_planner_channel',
                'delivery_planner_pref_changed',
                payload,
            )
        except Exception:
            _logger.debug('Failed to send delivery_planner_pref_changed notification', exc_info=True)

    # ---------------- Public RPC API ----------------

    @api.model
    def get_user_preferences(self):
        """Return current user's archived + consolidate SO ids + default filters."""
        rec = self._get_or_create_for_current_user()
        archived, consolidate = self._get_global_buckets()
        try:
            default_filters = json.loads(rec.default_filters_json or '{}')
        except (ValueError, TypeError):
            default_filters = {}
        return {
            'archived_so_ids': list(archived),
            'consolidate_so_ids': list(consolidate),
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
        current, consolidate = self._get_global_buckets()
        if so_id in current:
            current.discard(so_id)
        else:
            if self.env['sale.order'].browse(so_id).exists():
                current.add(so_id)
                consolidate.discard(so_id)
        self._save_global_buckets(current, consolidate)
        snap = self._snapshot()
        self._broadcast_pref_changed(snap, action='toggle_archive', so_id=so_id)
        return snap

    @api.model
    def toggle_consolidate(self, so_id):
        """Toggle consolidate (chờ gom) state for a single SO.

        Nếu đơn đang ở bucket archive → tự chuyển sang consolidate.
        """
        if not so_id:
            return self._snapshot()
        so_id = int(so_id)
        archived, current = self._get_global_buckets()
        if so_id in current:
            current.discard(so_id)
        else:
            if self.env['sale.order'].browse(so_id).exists():
                current.add(so_id)
                archived.discard(so_id)
        self._save_global_buckets(archived, current)
        snap = self._snapshot()
        self._broadcast_pref_changed(snap, action='toggle_consolidate', so_id=so_id)
        return snap

    @api.model
    def set_archived(self, so_ids):
        """Replace the archived set (used by 'phục hồi tất cả' / bulk ops)."""
        archived = set(self._sanitize_so_ids(so_ids or []))
        _, consolidate = self._get_global_buckets()
        consolidate -= archived
        self._save_global_buckets(archived, consolidate)
        snap = self._snapshot()
        self._broadcast_pref_changed(snap, action='set_archived')
        return snap

    @api.model
    def set_consolidate(self, so_ids):
        """Replace the consolidate set (used by 'phục hồi tất cả' / bulk ops)."""
        consolidate = set(self._sanitize_so_ids(so_ids or []))
        archived, _ = self._get_global_buckets()
        archived -= consolidate
        self._save_global_buckets(archived, consolidate)
        snap = self._snapshot()
        self._broadcast_pref_changed(snap, action='set_consolidate')
        return snap

    def _snapshot(self, rec=None):
        archived, consolidate = self._get_global_buckets()
        return {
            'archived_so_ids': list(archived),
            'consolidate_so_ids': list(consolidate),
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
