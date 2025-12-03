# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
from .wordpress_api import PriceSyncService
import logging

_logger = logging.getLogger(__name__)


class WordPressPriceSyncWizard(models.TransientModel):
    """
    Wizard để đồng bộ giá thủ công lên WordPress
    """
    _name = 'wordpress.price.sync'
    _description = 'WordPress Price Sync Wizard'

    # ===========================================
    # FIELDS
    # ===========================================
    sync_mode = fields.Selection([
        ('single', 'Một sản phẩm'),
        ('all', 'Tất cả sản phẩm'),
    ], string='Chế độ', default='single', required=True)

    product_id = fields.Many2one(
        'product.template',
        string='Sản phẩm'
    )

    wordpress_config_id = fields.Many2one(
        'wordpress.config',
        string='Cấu hình WordPress',
        required=True,
        domain=[('active', '=', True)],
        default=lambda self: self._default_wordpress_config()
    )

    # Computed field để kiểm tra có nhiều config không
    has_multiple_configs = fields.Boolean(
        compute='_compute_has_multiple_configs'
    )

    # ===========================================
    # DEFAULT / COMPUTE METHODS
    # ===========================================
    @api.model
    def _default_wordpress_config(self):
        """Lấy config mặc định từ Settings hoặc config active đầu tiên"""
        ICP = self.env['ir.config_parameter'].sudo()
        config_id = ICP.get_param('wordpress_sync.default_config_id', False)

        if config_id:
            try:
                config = self.env['wordpress.config'].browse(int(config_id))
                if config.exists() and config.active:
                    return config
            except (ValueError, TypeError):
                pass

        # Fallback: lấy config active đầu tiên
        return self.env['wordpress.config'].search([('active', '=', True)], limit=1)

    @api.depends('wordpress_config_id')
    def _compute_has_multiple_configs(self):
        """Kiểm tra có nhiều hơn 1 config active không"""
        config_count = self.env['wordpress.config'].search_count([('active', '=', True)])
        for record in self:
            record.has_multiple_configs = config_count > 1

    # ===========================================
    # ACTIONS
    # ===========================================
    def action_sync(self):
        """Thực hiện đồng bộ"""
        self.ensure_one()

        if not self.wordpress_config_id:
            raise UserError('Vui lòng chọn cấu hình WordPress')

        # Kiểm tra credentials
        wc_key, wc_secret = self.wordpress_config_id.get_credentials()
        if not wc_key or not wc_secret:
            raise UserError('Chưa cấu hình API credentials cho WordPress')

        if self.sync_mode == 'single':
            return self._sync_single()
        else:
            return self._sync_all()

    def _sync_single(self):
        """Đồng bộ một sản phẩm"""
        if not self.product_id:
            raise UserError('Vui lòng chọn sản phẩm cần đồng bộ')

        service = PriceSyncService(self.env, self.wordpress_config_id)
        result = service.sync_product(self.product_id)

        # Log kết quả
        self._create_log(self.product_id, result, 'manual')

        # Hiển thị notification
        if result['success']:
            return self._notify('Thành công', f"{self.product_id.name}: {result['message']}", 'success')
        else:
            return self._notify('Thất bại', result['message'], 'danger')

    def _sync_all(self):
        """Đồng bộ tất cả sản phẩm có SKU"""
        products = self.env['product.template'].search([
            ('active', '=', True),
            ('default_code', '!=', False),
            ('default_code', '!=', '')
        ])

        if not products:
            return self._notify('Không có sản phẩm', 'Không tìm thấy sản phẩm nào có SKU', 'warning')

        service = PriceSyncService(self.env, self.wordpress_config_id)

        success = 0
        failed = 0
        skipped = 0

        for product in products:
            result = service.sync_product(product)

            if result['success']:
                success += 1
                self._create_log(product, result, 'manual')
            elif 'không hợp lệ' in result['message'].lower() or 'không có sku' in result['message'].lower():
                skipped += 1
            else:
                failed += 1
                self._create_log(product, result, 'manual')

        # Update last sync date
        self.wordpress_config_id.last_sync_date = fields.Datetime.now()

        message = f'Thành công: {success}, Thất bại: {failed}, Bỏ qua: {skipped}'
        _logger.info(f"Bulk sync completed: {message}")

        return self._notify('Hoàn tất đồng bộ', message, 'success')

    # ===========================================
    # HELPER METHODS
    # ===========================================
    def _create_log(self, product, result, sync_type):
        """Tạo log đồng bộ"""
        status = 'success' if result['success'] else 'failed'
        self.env['product.sync.log'].create_log(
            product=product,
            status=status,
            message=result['message'],
            sync_type=sync_type,
            sku=result.get('sku', ''),
            wc_product_id=result.get('wc_product_id', ''),
            new_regular_price=result.get('regular_price', 0),
            new_sale_price=result.get('sale_price', 0)
        )

    def _notify(self, title, message, notif_type='info'):
        """Hiển thị notification"""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': notif_type,
                'sticky': False,
            }
        }
