# -*- coding: utf-8 -*-

from odoo import models, fields, api

# Mapping Shopee status → Vietnamese label
SHOPEE_STATUS_MAP = {
    'UNPAID': 'Chờ thanh toán',
    'READY_TO_SHIP': 'Chờ lấy hàng',
    'PROCESSED': 'Đã xử lý',
    'SHIPPED': 'Đang giao hàng',
    'COMPLETED': 'Hoàn thành',
    'IN_CANCEL': 'Chờ hủy',
    'CANCELLED': 'Đã hủy',
    'INVOICE_PENDING': 'Chờ hóa đơn',
    'RETRY_SHIP': 'Giao lại',
    'PENDING': 'Đang chờ xử lý',
}

SHOPEE_STATUS_SELECTION = [(k, v) for k, v in SHOPEE_STATUS_MAP.items()]


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    shopee_order_status = fields.Char(
        string='Trạng thái Shopee',
        help="Giá trị trạng thái gốc từ Shopee API",
        readonly=True,
        copy=False,
    )
    shopee_order_status_display = fields.Selection(
        selection=SHOPEE_STATUS_SELECTION,
        string='Trạng thái Shopee',
        compute='_compute_shopee_order_status_display',
        store=False,
        readonly=True,
    )

    @api.depends('shopee_order_status')
    def _compute_shopee_order_status_display(self):
        valid_keys = {k for k, _ in SHOPEE_STATUS_SELECTION}
        for order in self:
            raw = order.shopee_order_status or ''
            order.shopee_order_status_display = raw if raw in valid_keys else False
