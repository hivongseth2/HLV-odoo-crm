# -*- coding: utf-8 -*-
import json
from odoo import models, fields, api, _


class MisaCrmWebhookLog(models.Model):
    """
    Ghi lại mọi webhook nhận từ MISA AMIS CRM.
    Mỗi request HTTP = 1 bản ghi log.
    """
    _name = 'misa.crm.webhook.log'
    _description = 'MISA CRM Webhook Log'
    _order = 'create_date desc'
    _rec_name = 'display_name'

    # ─── Định danh ────────────────────────────────────────────────────────────
    event_type = fields.Char(
        'Loại sự kiện',
        index=True,
        help='Ví dụ: customer.created, customer.updated, order.created, order.updated',
    )
    app_id = fields.Char(
        'AppID (CRM)',
        help='AppID do MISA CRM gửi kèm trong payload',
    )
    crm_object_id = fields.Char(
        'ID đối tượng (CRM)',
        index=True,
        help='ID của khách hàng / đơn hàng bên MISA CRM',
    )

    # ─── Trạng thái ───────────────────────────────────────────────────────────
    state = fields.Selection([
        ('received',   'Đã nhận'),
        ('processing', 'Đang xử lý'),
        ('done',       'Thành công'),
        ('error',      'Lỗi'),
        ('ignored',    'Bỏ qua'),
    ], string='Trạng thái', default='received', required=True, index=True)

    http_method = fields.Char('HTTP Method', default='POST', readonly=True)
    http_status  = fields.Integer('HTTP Status trả về', default=200)

    # ─── Payload & lỗi ────────────────────────────────────────────────────────
    raw_payload = fields.Text(
        'Raw Payload (JSON)',
        readonly=True,
        help='Toàn bộ body JSON nhận từ MISA CRM',
    )
    error_message = fields.Text('Thông báo lỗi')
    note = fields.Text('Ghi chú xử lý')

    # ─── Liên kết Odoo ────────────────────────────────────────────────────────
    partner_id = fields.Many2one(
        'res.partner',
        string='Khách hàng Odoo',
        ondelete='set null',
        readonly=True,
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Đơn hàng Odoo',
        ondelete='set null',
        readonly=True,
    )

    # ─── Audit ────────────────────────────────────────────────────────────────
    create_date    = fields.Datetime('Thời gian nhận', readonly=True)
    processed_date = fields.Datetime('Thời gian xử lý', readonly=True)

    # ─── Compute ──────────────────────────────────────────────────────────────
    display_name = fields.Char(compute='_compute_display_name', store=True)

    @api.depends('event_type', 'crm_object_id', 'create_date')
    def _compute_display_name(self):
        for rec in self:
            parts = filter(None, [rec.event_type, rec.crm_object_id])
            rec.display_name = ' | '.join(parts) or _('Webhook #%d') % (rec.id or 0)

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def get_payload_dict(self):
        """Parse raw_payload JSON → dict. Trả về {} nếu lỗi."""
        try:
            return json.loads(self.raw_payload or '{}')
        except Exception:
            return {}

    def action_retry(self):
        """Retry xử lý webhook bị lỗi."""
        self.ensure_one()
        if self.state not in ('error', 'ignored'):
            return
        processor = self.env['misa.crm.processor']
        processor.process_log(self)

    def action_view_payload(self):
        """Hiển thị payload đẹp hơn (formatted JSON)."""
        self.ensure_one()
        try:
            pretty = json.dumps(json.loads(self.raw_payload or '{}'),
                                ensure_ascii=False, indent=2)
        except Exception:
            pretty = self.raw_payload or ''
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title':   _('Raw Payload'),
                'message': pretty[:500] + ('…' if len(pretty) > 500 else ''),
                'type':    'info',
                'sticky': True,
            },
        }
