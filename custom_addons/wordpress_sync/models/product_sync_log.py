# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import timedelta
import logging

_logger = logging.getLogger(__name__)


class ProductSyncLog(models.Model):
    """
    Log lịch sử đồng bộ giá lên WordPress
    """
    _name = 'product.sync.log'
    _description = 'Product Price Sync Log'
    _order = 'sync_date desc'

    # ===========================================
    # FIELDS
    # ===========================================
    product_id = fields.Many2one(
        'product.template',
        string='Sản phẩm',
        ondelete='cascade',
        required=True,
        index=True
    )

    sku = fields.Char(
        string='SKU',
        index=True
    )

    sync_type = fields.Selection([
        ('auto', 'Tự động'),
        ('manual', 'Thủ công'),
    ], string='Loại sync', default='auto')

    status = fields.Selection([
        ('success', 'Thành công'),
        ('failed', 'Thất bại'),
        ('skipped', 'Bỏ qua'),
    ], string='Trạng thái', required=True, index=True)

    message = fields.Text(string='Chi tiết')

    wc_product_id = fields.Char(string='WC Product ID')

    sync_date = fields.Datetime(
        string='Thời gian',
        default=fields.Datetime.now,
        readonly=True,
        index=True
    )

    # Price fields
    old_regular_price = fields.Float(string='Giá cũ (Regular)')
    new_regular_price = fields.Float(string='Giá mới (Regular)')
    old_sale_price = fields.Float(string='Giá cũ (Sale)')
    new_sale_price = fields.Float(string='Giá mới (Sale)')

    # User tracking
    user_id = fields.Many2one(
        'res.users',
        string='Người thực hiện',
        default=lambda self: self.env.user,
        readonly=True
    )

    # ===========================================
    # METHODS
    # ===========================================
    @api.model
    def create_log(self, product, status, message, sync_type='auto', **kwargs):
        """
        Helper method để tạo log

        Args:
            product: product.template record
            status: 'success', 'failed', 'skipped'
            message: Log message
            sync_type: 'auto' hoặc 'manual'
            **kwargs: Các field khác (sku, wc_product_id, prices...)

        Returns:
            product.sync.log record
        """
        vals = {
            'product_id': product.id,
            'status': status,
            'message': message,
            'sync_type': sync_type,
            'sku': kwargs.get('sku', product.default_code or ''),
            'wc_product_id': kwargs.get('wc_product_id', ''),
            'old_regular_price': kwargs.get('old_regular_price', 0),
            'new_regular_price': kwargs.get('new_regular_price', 0),
            'old_sale_price': kwargs.get('old_sale_price', 0),
            'new_sale_price': kwargs.get('new_sale_price', 0),
        }
        return self.create(vals)

    @api.model
    def cleanup_old_logs(self, days=None):
        """
        Xóa các log cũ hơn số ngày quy định

        Args:
            days: Số ngày giữ log. Nếu None, lấy từ config.
        """
        if days is None:
            config = self.env['wordpress.config'].search([('active', '=', True)], limit=1)
            days = config.sync_log_days if config else 30

        cutoff = fields.Datetime.now() - timedelta(days=days)
        old_logs = self.search([('sync_date', '<', cutoff)])
        count = len(old_logs)

        if count > 0:
            old_logs.unlink()
            _logger.info(f"Cleaned up {count} old sync logs (older than {days} days)")

        return count
