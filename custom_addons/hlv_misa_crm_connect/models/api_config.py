# -*- coding: utf-8 -*-
"""Màn "Cấu hình" của app MISA CRM API: bật/tắt API, cho phép ghi, API key.

Một bản ghi cố định duy nhất (data/api_config_data.xml) — menu mở thẳng bản ghi đó, không tạo mới.
Giá trị thật vẫn nằm ở System Parameter (controller đọc từ đó): các trường chỉ đọc / ghi qua
tham số, bản ghi chỉ là chỗ để form hiển thị. Màn riêng thay vì Cài đặt chung để người có quyền
"Quản lý API MISA CRM" tự quản lý được mà không cần quyền admin.
"""
import secrets

from odoo import fields, models

# Tắt = mọi route /api/misa-crm/* trả 503, kể cả key đúng.
PARAM_ENABLED = "hlv_misa_crm_connect.enabled"
# Quyền GHI lên MISA (tạo cơ hội…) tách riêng: bật API để tra cứu không có nghĩa là cho tạo dữ liệu.
PARAM_ALLOW_WRITE = "hlv_misa_crm_connect.allow_write"
# Key bên ngoài gửi ở header X-API-Key. Trống = cửa đóng.
PARAM_KEY = "hlv_misa_crm_connect.api_key"


class MisaCrmApiConfig(models.Model):
    _name = "hlv.misa.crm.api.config"
    _description = "Cấu hình API MISA CRM"

    name = fields.Char(default="Cấu hình API MISA CRM")
    # Không @api.depends: nguồn là System Parameter, không phải trường nào. Mỗi lần mở form / bấm
    # nút là một request mới nên luôn đọc giá trị mới nhất.
    enabled = fields.Boolean(string="Bật API", compute="_compute_params", inverse="_inverse_enabled")
    allow_write = fields.Boolean(string="Cho phép tạo dữ liệu trên MISA", compute="_compute_params",
                                 inverse="_inverse_allow_write")
    api_key = fields.Char(string="API key", compute="_compute_params")
    base_url = fields.Char(string="Địa chỉ gọi", compute="_compute_params")

    def _compute_params(self):
        params = self.env["ir.config_parameter"].sudo()
        for config in self:
            config.enabled = bool(params.get_param(PARAM_ENABLED))
            config.allow_write = bool(params.get_param(PARAM_ALLOW_WRITE))
            config.api_key = params.get_param(PARAM_KEY) or False
            config.base_url = (params.get_param("web.base.url") or "").rstrip("/") + "/api/misa-crm/"

    # set_param(False) xoá tham số — get_param trả None, controller hiểu là tắt.
    def _inverse_enabled(self):
        self.env["ir.config_parameter"].sudo().set_param(PARAM_ENABLED, self[-1:].enabled or False)

    def _inverse_allow_write(self):
        self.env["ir.config_parameter"].sudo().set_param(PARAM_ALLOW_WRITE, self[-1:].allow_write or False)

    def action_new_key(self):
        """Tạo key mới — key cũ hết hiệu lực ngay, bên gọi phải đổi sang key mới."""
        self.env["ir.config_parameter"].sudo().set_param(PARAM_KEY, secrets.token_urlsafe(32))
