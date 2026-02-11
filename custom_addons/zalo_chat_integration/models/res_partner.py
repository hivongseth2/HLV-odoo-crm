# -*- coding: utf-8 -*-
from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    zalo_summary_html = fields.Html(
        string='Zalo Assistant Summary',
        sanitize=False,
        help='Tóm tắt hội thoại từ Zalo (nội bộ).'
    )
    zalo_last_assistant_run = fields.Datetime(
        string='Zalo Assistant Last Run',
        readonly=True,
    )
