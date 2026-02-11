# -*- coding: utf-8 -*-
from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    zalo_user_id = fields.Char(
        string='Zalo User ID',
        index=True,
        help='ID người dùng Zalo liên kết với liên hệ này.'
    )

    zalo_summary_html = fields.Html(
        string='Zalo Assistant Summary',
        sanitize=False,
        help='Tóm tắt hội thoại từ Zalo (nội bộ).'
    )
    zalo_last_assistant_run = fields.Datetime(
        string='Zalo Assistant Last Run',
        readonly=True,
    )

    zalo_conversation_count = fields.Integer(
        string='Zalo Conversations',
        compute='_compute_zalo_conversation_count',
    )

    def _compute_zalo_conversation_count(self):
        Conv = self.env['zalo.chat.conversation']
        for partner in self:
            partner.zalo_conversation_count = Conv.search_count([
                ('partner_id', '=', partner.id)
            ])
