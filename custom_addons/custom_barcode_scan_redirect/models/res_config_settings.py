# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    require_assigned_packer = fields.Boolean(
        string='Chỉ người được assign mới vào được đóng gói',
        config_parameter='custom_barcode.require_assigned_packer',
        help='Nếu bật, chỉ người dùng được gán vào trường "Người đóng hàng" mới có thể mở giao diện đóng gói. '
             'Admin (Administrator) luôn được phép vào.',
    )
