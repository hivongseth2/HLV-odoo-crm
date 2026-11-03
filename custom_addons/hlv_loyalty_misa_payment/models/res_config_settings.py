# -*- coding: utf-8 -*-
from odoo import fields, models

from .loyalty_history_sale_confirm import SALE_ALLOW_CANCEL_PARAM, SALE_ALLOW_EDIT_PARAM


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    loyalty_sale_allow_cancel = fields.Boolean(
        string='Sale được hủy điểm chờ xác nhận',
        config_parameter=SALE_ALLOW_CANCEL_PARAM,
    )
    loyalty_sale_allow_edit = fields.Boolean(
        string='Sale được sửa / tính lại điểm chờ xác nhận',
        config_parameter=SALE_ALLOW_EDIT_PARAM,
    )
