# -*- coding: utf-8 -*-
from odoo import models, fields, api
from .wordpress_api import PriceSyncService, StockSyncService
from datetime import datetime
import logging

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    """
    Extension cho product.template để hỗ trợ auto-sync giá và stock lên WordPress
    """
    _inherit = 'product.template'

    # ===========================================
    # NEW FIELDS
    # ===========================================
    x_wp_combo_price = fields.Float(
        string='Giá bán trong combo',
        default=0.0,
        help='Giá sử dụng khi tính giá combo (nếu = 0, sử dụng giá bán thường)'
    )

    computed_combo_selling_price = fields.Float(
        string='Giá combo tính toán',
        compute='_compute_combo_selling_price',
        store=False,
        help='Giá bán combo được tính tự động từ BOM'
    )

    # ===========================================
    # COMPUTED METHODS
    # ===========================================
    @api.depends('bom_ids', 'bom_ids.bom_line_ids')
    def _compute_combo_selling_price(self):
        """Tính giá combo dựa trên BOM và phương pháp được cấu hình"""
        # Get settings from wordpress.config
        config = self._get_wordpress_config()
        if config:
            pricing_method = config.combo_pricing_method or 'sum_combo_price'
            discount_pct = config.combo_discount_percentage or 0.0
        else:
            pricing_method = 'sum_combo_price'
            discount_pct = 0.0

        for product in self:
            product.computed_combo_selling_price = product._calculate_combo_price(
                pricing_method, discount_pct
            )

    def _calculate_combo_price(self, pricing_method='sum_combo_price', discount_pct=0.0):
        """
        Tính giá combo dựa trên BOM

        Args:
            pricing_method: 'sum_combo_price' hoặc 'discount_percentage'
            discount_pct: Phần trăm giảm giá (0-100)

        Returns:
            float: Giá combo tính toán
        """
        self.ensure_one()

        # Find active BOM for this product (phantom/kit type)
        bom = self.env['mrp.bom'].search([
            ('product_tmpl_id', '=', self.id),
            ('type', '=', 'phantom'),
            ('active', '=', True)
        ], limit=1)

        if not bom:
            return 0.0

        total_price = 0.0

        for line in bom.bom_line_ids:
            child_product = line.product_id.product_tmpl_id
            qty = line.product_qty or 1.0

            if pricing_method == 'sum_combo_price':
                # Lấy x_wp_combo_price, nếu = 0 thì lấy giá bán thường
                combo_price = child_product.x_wp_combo_price or 0.0
                if combo_price <= 0:
                    # Fallback to regular price (x_studio_ga_web or list_price)
                    combo_price = getattr(child_product, 'x_studio_ga_web', 0) or child_product.list_price or 0.0
                total_price += combo_price * qty
            else:
                # discount_percentage method
                regular_price = getattr(child_product, 'x_studio_ga_web', 0) or child_product.list_price or 0.0
                total_price += regular_price * qty

        # Apply discount if using discount_percentage method
        if pricing_method == 'discount_percentage' and discount_pct > 0:
            total_price = total_price * (1 - discount_pct / 100)

        return total_price

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

    def action_sync_stock_to_wordpress(self):
        """Button action để sync stock status thủ công"""
        self.ensure_one()

        config = self._get_wordpress_config()
        if not config:
            return self._notify('Thiếu cấu hình', 'Không tìm thấy cấu hình WordPress', 'warning')

        wc_key, wc_secret = config.get_credentials()
        if not wc_key or not wc_secret:
            return self._notify('Thiếu Credentials', 'Vui lòng nhập Consumer Key và Secret', 'warning')

        service = StockSyncService(self.env, config)
        result = service.sync_stock_status(self)

        if result['success']:
            # Create log
            self.env['product.sync.log'].create_log(
                product=self,
                status='success',
                message=f"Stock: {result['message']}",
                sync_type='manual',
                sku=result.get('sku', ''),
                wc_product_id=result.get('wc_product_id', '')
            )
            self._post_sync_note(self, result)
            return self._notify('Thành công', result['message'], 'success')
        else:
            self.env['product.sync.log'].create_log(
                product=self,
                status='failed',
                message=f"Stock: {result['message']}",
                sync_type='manual',
                sku=result.get('sku', self.default_code or ''),
                wc_product_id=result.get('wc_product_id', '')
            )
            return self._notify('Thất bại', result['message'], 'danger')

    # ===========================================
    # PRIVATE METHODS
    # ===========================================
    def _is_auto_sync_enabled(self):
        """Kiểm tra auto-sync có được bật không"""
        config = self._get_wordpress_config()
        if config:
            return config.auto_sync_price
        return False

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
            stock_status = result.get('stock_status', '')

            if stock_status:
                body = (
                    f"✓ WordPress Stock Sync thành công\n"
                    f"Stock Status: {stock_status}\n"
                    f"Người thực hiện: {self.env.user.name}\n"
                    f"Thời gian: {sync_time}"
                )
            else:
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

    def _notify(self, title, message, notif_type='info'):
        """Hiển thị notification cho user"""
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

