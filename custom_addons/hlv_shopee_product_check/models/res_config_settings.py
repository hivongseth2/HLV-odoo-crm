# -*- coding: utf-8 -*-
from odoo import fields, models

from odoo.addons.hlv_product_agent.services.claude_api_payload import MODEL_CHOICES

from .shopee_product_check import DEFAULT_AI_MODEL, PARAM_AI_MODEL
from .shopee_product_check_auto import DEFAULT_INTERVAL_DAYS, PARAM_AUTO, PARAM_INTERVAL


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    hlv_shopee_check_auto = fields.Boolean(
        "Tự kiểm map nhầm Shopee định kỳ", config_parameter=PARAM_AUTO,
        help="Mỗi đêm Odoo xem đã đủ số ngày chưa; đủ thì kiểm mọi liên kết của các shop đang kết nối, "
             "có map nhầm thì báo người có quyền sửa liên kết Shopee.")
    hlv_shopee_check_interval = fields.Integer(
        "Chu kỳ (ngày)", default=DEFAULT_INTERVAL_DAYS, config_parameter=PARAM_INTERVAL)
    hlv_shopee_check_ai_model = fields.Selection(
        MODEL_CHOICES, string="Model AI mặc định", default=DEFAULT_AI_MODEL, config_parameter=PARAM_AI_MODEL,
        help="Dùng cho lần kiểm mới (tạo tay, từ danh sách Sản phẩm Shopee, và tự kiểm định kỳ). Lần kiểm đã "
             "Xong / Lỗi vẫn đổi được model riêng trên form rồi Chạy lại AI.")
