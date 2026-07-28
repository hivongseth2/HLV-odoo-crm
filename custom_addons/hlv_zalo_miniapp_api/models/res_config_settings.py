# -*- coding: utf-8 -*-
from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    x_zalo_oa_id = fields.Char(
        string='Zalo OA ID',
        config_parameter='hlv_zalo_miniapp.oa_id',
        default='3668388836585145887',
        help='ID tài khoản Zalo Official Account (OA)',
    )
    x_zalo_oa_name = fields.Char(
        string='Tên Zalo OA',
        config_parameter='hlv_zalo_miniapp.oa_name',
        default='Hoàng Long Vũ',
        help='Tên Zalo OA hiển thị trên Mini App',
    )
    x_zalo_oa_subtext = fields.Char(
        string='Mô tả ngắn OA',
        config_parameter='hlv_zalo_miniapp.oa_subtext',
        default='Theo dõi OA để nhận thông tin khuyến mãi, bảo hành và ưu đãi mới nhất!',
        help='Mô tả ngắn hiển thị trên thẻ kết nối OA',
    )
