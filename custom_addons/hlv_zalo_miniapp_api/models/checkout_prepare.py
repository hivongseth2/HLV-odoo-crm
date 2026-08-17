# -*- coding: utf-8 -*-
from odoo import fields, models


class ZaloCheckoutPrepare(models.Model):
    _name = "zalo.miniapp.checkout.prepare"
    _description = "Chuẩn bị đơn hàng Zalo Checkout SDK (chưa tạo sale.order)"

    token = fields.Char(string="Token chuẩn bị", index=True, required=True)
    order_name = fields.Char(string="Mã đơn dự kiến", index=True)
    partner_id = fields.Many2one(
        "res.partner", string="Khách hàng", required=True, ondelete="cascade"
    )
    items = fields.Text(string="Danh sách sản phẩm (JSON)")
    address_id = fields.Integer(string="Địa chỉ giao hàng")
    note = fields.Text(string="Ghi chú")
    payment_method = fields.Char(string="Phương thức thanh toán")
    amount = fields.Float(string="Tổng tiền")
    desc = fields.Char(string="Mô tả đơn")
    item_sdk = fields.Text(string="SDK items (JSON)")
    extradata_str = fields.Text(string="Extradata (JSON string)")
    method_str = fields.Text(string="Method (JSON string)")
    mac = fields.Char(string="MAC signature")

    active = fields.Boolean(string="Còn hiệu lực", default=True)
    consumed = fields.Boolean(string="Đã xác nhận đơn", default=False)
