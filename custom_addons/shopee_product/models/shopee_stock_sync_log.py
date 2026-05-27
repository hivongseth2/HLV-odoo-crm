# -*- coding: utf-8 -*-
"""
models/shopee_stock_sync_log.py

Lịch sử đồng bộ tồn kho Shopee.

Mỗi khi _mark_for_stock_sync() đánh dấu một shopee.product, một log entry
được tạo (hoặc cập nhật nếu đã có entry pending cho sản phẩm đó). Khi cron
xử lý xong, entry được cập nhật thành 'done' hoặc 'error'.

Dùng để theo dõi:
- Sản phẩm nào đang chờ đồng bộ
- Khi nào được trigger (picking nào xác nhận)
- Kết quả đẩy: thành công / lỗi (có message)
- Tồn kho thực tế đã đẩy lên Shopee
"""
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class ShopeeStockSyncLog(models.Model):
    _name = 'shopee.stock.sync.log'
    _description = 'Lịch sử đồng bộ tồn kho Shopee'
    _order = 'triggered_at desc, id desc'
    _rec_name = 'item_name'

    shopee_product_id = fields.Many2one(
        'shopee.product',
        string='Sản phẩm Shopee',
        ondelete='set null',
        index=True,
    )
    shop_id = fields.Many2one(
        'shopee.shop',
        string='Cửa hàng',
        related='shopee_product_id.shop_id',
        store=True,
        index=True,
    )
    item_name = fields.Char(
        string='Tên sản phẩm',
        related='shopee_product_id.item_name',
        store=True,
    )
    shopee_item_id = fields.Char(
        string='Shopee Item ID',
        related='shopee_product_id.shopee_item_id',
        store=True,
    )

    state = fields.Selection([
        ('pending', 'Chờ xử lý'),
        ('done', 'Thành công'),
        ('error', 'Lỗi'),
    ], string='Trạng thái', default='pending', index=True, required=True)

    triggered_at = fields.Datetime(
        string='Đánh dấu lúc',
        default=fields.Datetime.now,
        readonly=True,
    )
    synced_at = fields.Datetime(string='Đồng bộ lúc', readonly=True)

    stock_qty = fields.Integer(string='Tồn kho đã đẩy', readonly=True)
    error_message = fields.Text(string='Thông báo lỗi', readonly=True)
