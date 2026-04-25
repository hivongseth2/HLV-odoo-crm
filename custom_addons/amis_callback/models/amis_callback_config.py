# -*- coding: utf-8 -*-
from odoo import fields, models


class AmisCallbackConfig(models.Model):
    _name = 'amis.callback.config'
    _description = 'AMIS Callback Configuration'

    name = fields.Char(default='AMIS Callback', required=True)
    app_id = fields.Char(
        string='App ID',
        help='MISA app_id dùng làm key để xác thực signature HMAC SHA256.',
        required=True,
        default='cfd435c9-b5c9-484f-b86d-ddbba36dc0f4',
    )
    callback_route = fields.Char(
        string='Callback Route',
        default='/api/oauth/actopensupport/call_back_data',
        readonly=True,
    )
    active = fields.Boolean(default=True)
    note = fields.Text(
        string='Note',
        default='Cập nhật app_id đúng với giá trị MISA cấp cho hệ thống của bạn.',
    )

    def ensure_singleton(self):
        record = self.search([], limit=1)
        if record:
            return record
        return self.create({
            'name': 'AMIS Callback',
        })
