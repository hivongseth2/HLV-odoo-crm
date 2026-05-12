# -*- coding: utf-8 -*-
from odoo import fields, models


class AmisShopeeWebhookStatus(models.Model):
    """Danh sách trạng thái Shopee có thể kích hoạt auto-publish meInvoice."""

    _name = 'amis.shopee.webhook.status'
    _description = 'Trạng thái Shopee kích hoạt Webhook Queue'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    name = fields.Char(string='Trạng thái', required=True)
    shopee_code = fields.Char(string='Mã Shopee (EN)', help='Ví dụ: COMPLETED')
