# -*- coding: utf-8 -*-
from odoo import models, fields
from .wordpress_api import PriceSyncService
from datetime import datetime
import logging

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    """
    Extension cho product.template để hỗ trợ auto-sync giá lên WordPress
    """
    _inherit = 'product.template'

    # ===========================================
    # OVERRIDE METHODS
    # ===========================================
    def write(self, vals):
        """Override write để auto-sync khi giá thay đổi"""
        # Các field giá cần theo dõi
        price_fields = ['x_studio_ga_web', 'x_studio_gi_bn_thng_mi']
        has_price_change = any(field in vals for field in price_fields)

        result = super().write(vals)

        # Auto-sync nếu có thay đổi giá và đã bật trong settings
        if has_price_change and not self.env.context.get('skip_wordpress_sync'):
            if self._is_auto_sync_enabled():
                self._auto_sync_to_wordpress()

        return result

    # ===========================================
    # ACTIONS
    # ===========================================
    def action_sync_to_wordpress(self):
        """Button action để mở wizard sync thủ công"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'wordpress.price.sync',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_sync_mode': 'single',
                'default_product_id': self.id
            }
        }

    # ===========================================
    # PRIVATE METHODS
    # ===========================================
    def _is_auto_sync_enabled(self):
        """Kiểm tra auto-sync có được bật không"""
        value = self.env['ir.config_parameter'].sudo().get_param(
            'wordpress_sync.auto_sync_enabled', 'False'
        )
        return value in ('1', 'true', 'True', True)

    def _get_wordpress_config(self):
        """Lấy config WordPress để đồng bộ"""
        ICP = self.env['ir.config_parameter'].sudo()
        config_id = int(ICP.get_param('wordpress_sync.default_config_id', '0') or 0)

        if config_id:
            config = self.env['wordpress.config'].browse(config_id)
            if config.exists() and config.active:
                return config

        # Fallback: lấy config active đầu tiên
        return self.env['wordpress.config'].search([('active', '=', True)], limit=1)

    def _auto_sync_to_wordpress(self):
        """Tự động đồng bộ giá lên WordPress khi thay đổi"""
        config = self._get_wordpress_config()
        if not config:
            _logger.warning("Auto-sync: No active WordPress configuration found")
            return

        # Kiểm tra credentials
        wc_key, wc_secret = config.get_credentials()
        if not wc_key or not wc_secret:
            _logger.warning(f"Auto-sync: No credentials for config {config.name}")
            return

        # Khởi tạo service
        service = PriceSyncService(self.env, config)

        for product in self:
            # Bỏ qua product không có SKU
            if not product.default_code:
                continue

            try:
                result = service.sync_product(product)

                if result['success']:
                    _logger.info(f"Auto-synced: {product.name} (SKU: {product.default_code})")

                    # Tạo internal note trên product
                    self._post_sync_note(product, result)

                    # Tạo log
                    self.env['product.sync.log'].create_log(
                        product=product,
                        status='success',
                        message=result['message'],
                        sync_type='auto',
                        sku=result.get('sku', ''),
                        wc_product_id=result.get('wc_product_id', ''),
                        new_regular_price=result.get('regular_price', 0),
                        new_sale_price=result.get('sale_price', 0)
                    )
                else:
                    _logger.warning(f"Auto-sync failed: {product.name} - {result['message']}")

                    # Tạo internal note về lỗi
                    self._post_sync_note(product, result, success=False)

                    # Tạo log thất bại
                    self.env['product.sync.log'].create_log(
                        product=product,
                        status='failed',
                        message=result['message'],
                        sync_type='auto',
                        sku=result.get('sku', product.default_code or ''),
                        wc_product_id=result.get('wc_product_id', ''),
                        new_regular_price=result.get('regular_price', 0),
                        new_sale_price=result.get('sale_price', 0)
                    )

            except Exception as e:
                _logger.exception(f"Auto-sync error for {product.name}: {e}")

                # Tạo note cho exception
                error_result = {'message': str(e)}
                self._post_sync_note(product, error_result, success=False)

    def _post_sync_note(self, product, result, success=True):
        """Tạo internal note trên product sau khi sync"""
        sync_time = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        if success:
            regular_price = result.get('regular_price', 0)
            sale_price = result.get('sale_price', 0)
            sale_price_str = f"{sale_price:,.0f} đ" if sale_price > 0 else "Không có"

            body = (
                f"✓ WordPress Sync thành công\n"
                f"Regular Price: {regular_price:,.0f} đ\n"
                f"Sale Price: {sale_price_str}\n"
                f"Người thực hiện: {self.env.user.name}\n"
                f"Thời gian: {sync_time}"
            )
        else:
            error_message = result.get('message', 'Lỗi không xác định')

            body = (
                f"✗ WordPress Sync thất bại\n"
                f"Chi tiết lỗi: {error_message}\n"
                f"SKU: {product.default_code or 'Không có'}\n"
                f"Người thực hiện: {self.env.user.name}\n"
                f"Thời gian: {sync_time}"
            )

        product.message_post(
            body=body,
            message_type='comment',
            subtype_xmlid='mail.mt_note'
        )
