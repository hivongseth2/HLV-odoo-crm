# -*- coding: utf-8 -*-
from odoo import fields, models

from odoo.addons.hlv_product_agent.services.claude_api_payload import MODEL_CHOICES

from .vendor_import_ai import DEFAULT_MODEL, PARAM_MODEL


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    hlv_vendor_import_ai_model = fields.Selection(
        MODEL_CHOICES, string="Model AI duyệt file NCC", default=DEFAULT_MODEL, config_parameter=PARAM_MODEL,
        help="Claude so mã / tên trong file NCC với sản phẩm ứng viên bên mình. Dùng API key của Trợ lý tạo mã "
             "hàng (Cài đặt → Tồn kho). Opus kỹ nhất — ghép nhầm là đưa tồn của hàng này sang hàng khác.",
    )
