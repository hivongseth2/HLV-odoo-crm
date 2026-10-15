# -*- coding: utf-8 -*-
import secrets

from odoo import fields, models

# Tắt = mọi route /api/misa-crm/* trả 503, kể cả key đúng.
PARAM_ENABLED = "hlv_misa_crm_connect.enabled"
# Quyền GHI lên MISA (tạo cơ hội…) tách riêng: bật API để tra cứu không có nghĩa là cho tạo dữ liệu.
PARAM_ALLOW_WRITE = "hlv_misa_crm_connect.allow_write"
# Key bên ngoài gửi ở header X-API-Key. Trống = cửa đóng.
PARAM_KEY = "hlv_misa_crm_connect.api_key"


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    hlv_misa_crm_api_enabled = fields.Boolean(string="Bật API MISA CRM", config_parameter=PARAM_ENABLED)
    hlv_misa_crm_api_allow_write = fields.Boolean(string="Cho phép tạo dữ liệu trên MISA",
                                                  config_parameter=PARAM_ALLOW_WRITE)
    hlv_misa_crm_api_key = fields.Char(string="API key", config_parameter=PARAM_KEY, readonly=True)

    def action_hlv_misa_crm_new_key(self):
        """Tạo key mới — key cũ hết hiệu lực ngay, bên gọi phải đổi sang key mới."""
        self.env["ir.config_parameter"].sudo().set_param(PARAM_KEY, secrets.token_urlsafe(32))
        return {"type": "ir.actions.client", "tag": "reload"}
