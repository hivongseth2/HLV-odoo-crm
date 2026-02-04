# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # Define Studio fields explicitly to ensure they exist for the view
    # Note: If these fields already exist in the database (via Studio), 
    # declaring them here with the same name allows us to use them in code/views
    # without "Field not found" errors.

    x_studio_ga_web = fields.Monetary(string="Giá Web")
    x_studio_gi_bn_thng_mi = fields.Monetary(string="Giá Thương Mại")
    x_studio_ga_hng_nim_yt = fields.Monetary(string="Giá Niêm Yết")
    x_studio_gia_san_tmdt = fields.Monetary(string="Giá Sàn TMĐT")

    # WordPress stock status field
    x_wp_stock_status = fields.Selection([
        ('instock', 'Còn hàng'),
        ('outofstock', 'Hết hàng'),
        ('discontinued', 'Ngừng kinh doanh'),
    ], string='Tình trạng WP', default='instock',
       help='Tình trạng kho sản phẩm trên WordPress. Thay đổi field này sẽ tự động cập nhật lên WordPress.')

    # Bulk Editor Fields
    is_combo_product = fields.Boolean(
        string='Là Combo',
        compute='_compute_is_combo_product',
        store=True,
        index=True
    )
    
    bulk_product_type_label = fields.Selection([
        ('single', 'Sản phẩm lẻ'),
        ('combo', 'Combo')
    ], string='Loại sản phẩm', compute='_compute_bulk_product_type_label')

    @api.depends('bom_ids', 'bom_ids.type', 'bom_ids.active')
    def _compute_is_combo_product(self):
        for record in self:
            # Check for any phantom bom
            has_kit = False
            if hasattr(record, 'bom_ids'):
                has_kit = any(b.type == 'phantom' and b.active for b in record.bom_ids)
            record.is_combo_product = has_kit

    @api.depends('is_combo_product')
    def _compute_bulk_product_type_label(self):
        for record in self:
            record.bulk_product_type_label = 'combo' if record.is_combo_product else 'single'

    def write(self, vals):
        """Override write để sync WordPress stock status khi thay đổi"""
        result = super().write(vals)

        # Check if WordPress stock status was changed
        # DISABLED: Use wordpress_sync module instead (Async Queue)
        # if 'x_wp_stock_status' in vals and not self.env.context.get('skip_wordpress_sync'):
        #     self._sync_wp_stock_status()

        return result

    def _sync_wp_stock_status(self):
        """Sync WordPress stock status khi field thay đổi"""
        # Import here to avoid circular import
        try:
            from odoo.addons.wordpress_sync.models.wordpress_api import StockSyncService, WooCommerceAPI
        except ImportError:
            _logger.warning("wordpress_sync module not installed, skipping sync")
            return

        # Get WordPress config
        ICP = self.env['ir.config_parameter'].sudo()
        config_id = int(ICP.get_param('wordpress_sync.default_config_id', '0') or 0)

        config = None
        if config_id:
            config = self.env['wordpress.config'].browse(config_id)
            if not config.exists() or not config.active:
                config = None

        if not config:
            config = self.env['wordpress.config'].search([('active', '=', True)], limit=1)

        if not config:
            _logger.warning("No active WordPress configuration found for stock sync")
            return

        wc_key, wc_secret = config.get_credentials()
        if not wc_key or not wc_secret:
            _logger.warning("WordPress credentials not configured")
            return

        # Map status
        STATUS_MAP = {
            'instock': 'instock',
            'outofstock': 'outofstock',
            'discontinued': 'outofstock'  # Discontinued maps to outofstock in WooCommerce
        }

        api = WooCommerceAPI(config.wc_domain, wc_key, wc_secret)

        for product in self:
            sku = product.default_code
            if not sku:
                _logger.warning(f"Product {product.name} has no SKU, skipping WP sync")
                continue

            stock_status = STATUS_MAP.get(product.x_wp_stock_status, 'outofstock')

            try:
                # Find product on WordPress
                wc_product = api.find_product_by_sku(sku)
                if not wc_product:
                    _logger.warning(f"Product SKU {sku} not found on WordPress")
                    continue

                wc_id = wc_product.get('id')
                is_variation = wc_product.get('type') == 'variation'
                parent_id = wc_product.get('parent_id', 0) if is_variation else None

                # Update stock status
                payload = {'stock_status': stock_status}
                response = api.update_product(wc_id, payload, is_variation=is_variation, parent_id=parent_id)

                if response:
                    _logger.info(f"Updated WP stock status for {product.name} ({sku}): {stock_status}")

                    # Purge cache
                    api.purge_cache(config.cache_purge_url, sku)

                    # Create sync log if available
                    if 'product.sync.log' in self.env:
                        self.env['product.sync.log'].create_log(
                            product=product,
                            status='success',
                            message=f"Stock status: {stock_status}",
                            sync_type='manual',
                            sku=sku,
                            wc_product_id=str(wc_id)
                        )
                else:
                    _logger.error(f"Failed to update WP stock status for {product.name}")

            except Exception as e:
                _logger.exception(f"Error syncing WP stock for {product.name}: {e}")

