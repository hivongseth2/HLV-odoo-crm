# -*- coding: utf-8 -*-
"""Màn "Cấu hình" của app MISA CRM API: bật/tắt API, cho phép ghi, API key.

Giá trị lưu ở System Parameter (controller đọc từ đó). Màn riêng thay vì Cài đặt chung để
người có quyền "Quản lý API MISA CRM" tự quản lý được mà không cần quyền admin.
"""
import secrets

from odoo import api, fields, models

# Tắt = mọi route /api/misa-crm/* trả 503, kể cả key đúng.
PARAM_ENABLED = "hlv_misa_crm_connect.enabled"
# Quyền GHI lên MISA (tạo cơ hội…) tách riêng: bật API để tra cứu không có nghĩa là cho tạo dữ liệu.
PARAM_ALLOW_WRITE = "hlv_misa_crm_connect.allow_write"
# Key bên ngoài gửi ở header X-API-Key. Trống = cửa đóng.
PARAM_KEY = "hlv_misa_crm_connect.api_key"


class MisaCrmApiConfig(models.TransientModel):
    _name = "hlv.misa.crm.api.config"
    _description = "Cấu hình API MISA CRM"

    enabled = fields.Boolean(string="Bật API")
    allow_write = fields.Boolean(string="Cho phép tạo dữ liệu trên MISA")
    api_key = fields.Char(string="API key", readonly=True)
    base_url = fields.Char(string="Địa chỉ gọi", readonly=True)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        params = self.env["ir.config_parameter"].sudo()
        values.update({
            "enabled": bool(params.get_param(PARAM_ENABLED)),
            "allow_write": bool(params.get_param(PARAM_ALLOW_WRITE)),
            "api_key": params.get_param(PARAM_KEY) or False,
            "base_url": (params.get_param("web.base.url") or "").rstrip("/") + "/api/misa-crm/",
        })
        return values

    def action_save(self):
        self.ensure_one()
        params = self.env["ir.config_parameter"].sudo()
        # set_param(False) xoá tham số — get_param trả None, controller hiểu là tắt.
        params.set_param(PARAM_ENABLED, self.enabled or False)
        params.set_param(PARAM_ALLOW_WRITE, self.allow_write or False)
        return self._reopen()

    def action_new_key(self):
        """Tạo key mới — key cũ hết hiệu lực ngay, bên gọi phải đổi sang key mới."""
        self.env["ir.config_parameter"].sudo().set_param(PARAM_KEY, secrets.token_urlsafe(32))
        return self._reopen()

    def _reopen(self):
        return self.env["ir.actions.actions"]._for_xml_id("hlv_misa_crm_connect.action_api_config")
