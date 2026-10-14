# -*- coding: utf-8 -*-
from odoo import fields, models

from .shopee_product_check_auto import DEFAULT_INTERVAL_DAYS, PARAM_AUTO, PARAM_INTERVAL


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    hlv_shopee_check_auto = fields.Boolean(
        "Tự kiểm map nhầm Shopee định kỳ", config_parameter=PARAM_AUTO,
        help="Mỗi đêm Odoo xem đã đủ số ngày chưa; đủ thì kiểm mọi liên kết của các shop đang kết nối, "
             "có map nhầm thì báo người có quyền sửa liên kết Shopee.")
    hlv_shopee_check_interval = fields.Integer(
        "Chu kỳ (ngày)", default=DEFAULT_INTERVAL_DAYS, config_parameter=PARAM_INTERVAL)
