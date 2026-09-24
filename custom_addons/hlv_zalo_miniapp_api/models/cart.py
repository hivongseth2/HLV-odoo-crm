# -*- coding: utf-8 -*-
from odoo import fields, models


class ZaloMiniAppCartLine(models.Model):
    _name = "zalo.miniapp.cart.line"
    _description = "Zalo Mini App Cart Line"
    _order = "id desc"

    partner_id = fields.Many2one(
        "res.partner",
        string="Khách hàng",
        required=True,
        ondelete="cascade",
        index=True,
    )
    account_id = fields.Many2one(
        "hlv.loyalty.portal.account",
        string="Tài khoản Zalo",
        index=True,
        ondelete="cascade",
        help="Tài khoản Portal sở hữu dòng giỏ hàng này. `partner_id` là pháp "
             "nhân công ty, dùng chung cho nhiều người thu mua — chỉ lọc theo "
             "nó thì hai người cùng công ty sẽ thấy chung một giỏ, người này "
             "thêm hàng người kia thấy.",
    )
    product_id = fields.Many2one(
        "product.product",
        string="Sản phẩm",
        required=True,
        ondelete="cascade",
    )
    quantity = fields.Float(
        string="Số lượng",
        default=1.0,
        required=True,
    )
    price_unit = fields.Float(
        string="Đơn giá",
        compute="_compute_price_unit",
        store=True,
    )

    def _compute_price_unit(self):
        for line in self:
            if line.product_id:
                line.price_unit = line.product_id.x_zalo_price or line.product_id.list_price or 0.0
            else:
                line.price_unit = 0.0
