# -*- coding: utf-8 -*-
import secrets

from odoo import fields, models

# Khoá máy nghe dùng gọi /api/zalo-listener/* (header X-API-Key). Trống = cửa đóng, không nhận gì.
INGEST_KEY_PARAM = "hlv_vendor_zalo.ingest_key"


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    hlv_zalo_ingest_key = fields.Char(string="Khoá máy nghe Zalo", config_parameter=INGEST_KEY_PARAM, readonly=True)

    def action_hlv_zalo_new_key(self):
        """Tạo khoá mới — khoá cũ hết hiệu lực ngay, phải dán khoá mới vào file .env của máy nghe."""
        self.env["ir.config_parameter"].sudo().set_param(INGEST_KEY_PARAM, secrets.token_urlsafe(32))
        return {"type": "ir.actions.client", "tag": "reload"}
