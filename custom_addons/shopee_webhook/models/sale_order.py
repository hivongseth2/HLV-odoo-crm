# -*- coding: utf-8 -*-

from odoo import models, fields, api

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    shopee_order_status = fields.Selection(
        selection=[
            ('UNPAID', 'Chờ thanh toán'),
            ('READY_TO_SHIP', 'Chờ lấy hàng'),
            ('PROCESSED', 'Đã xử lý'),
            ('SHIPPED', 'Đang giao hàng'),
            ('COMPLETED', 'Hoàn thành'),
            ('IN_CANCEL', 'Chờ hủy'),
            ('CANCELLED', 'Đã hủy'),
            ('INVOICE_PENDING', 'Chờ hóa đơn'),
            ('RETRY_SHIP', 'Giao lại'),
            ('PENDING', 'Đang chờ xử lý'),
        ],
        string='Trạng thái Shopee',
        help="Trạng thái đơn hàng từ Shopee",
        readonly=True,
        copy=False,
    )
