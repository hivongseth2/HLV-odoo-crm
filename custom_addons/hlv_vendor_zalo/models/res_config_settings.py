# -*- coding: utf-8 -*-
import secrets

from odoo import fields, models
from odoo.addons.hlv_product_agent.services.claude_api_payload import MODEL_CHOICES

from .zalo_ai import DEFAULT_MODEL, PARAM_ENABLED, PARAM_MODEL
from .zalo_proposal import AUTO_APPLY_PARAM

# Khoá máy nghe dùng gọi /api/zalo-listener/* (header X-API-Key). Trống = cửa đóng, không nhận gì.
INGEST_KEY_PARAM = "hlv_vendor_zalo.ingest_key"


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    hlv_zalo_ingest_key = fields.Char(string="Khoá máy nghe Zalo", config_parameter=INGEST_KEY_PARAM, readonly=True)
    hlv_zalo_ai_enabled = fields.Boolean(string="AI đọc Zalo soạn giá cho báo giá", config_parameter=PARAM_ENABLED)
    hlv_zalo_ai_model = fields.Selection(MODEL_CHOICES, string="Model AI đọc Zalo", default=DEFAULT_MODEL,
                                         config_parameter=PARAM_MODEL)
    hlv_zalo_ai_auto_apply = fields.Boolean(string="AI tự ghi vào báo giá khi chắc chắn", config_parameter=AUTO_APPLY_PARAM)

    def action_hlv_zalo_new_key(self):
        """Tạo khoá mới — khoá cũ hết hiệu lực ngay, phải dán khoá mới vào file .env của máy nghe."""
        self.env["ir.config_parameter"].sudo().set_param(INGEST_KEY_PARAM, secrets.token_urlsafe(32))
        return {"type": "ir.actions.client", "tag": "reload"}
